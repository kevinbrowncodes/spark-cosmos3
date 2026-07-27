# Cosmos 3 video API reference

Extracted from this server's own `/openapi.json` and the installed
`vllm_omni` source (image `vllm/vllm-omni:cosmos3`), 2026-06-12. The upstream
docs are thinner than this — the server is the source of truth.

## The gateway (:8002) — what clients should actually call

Clients should not talk to vLLM-Omni directly. The gateway (`gateway/`,
container `cosmos3-gateway`) owns the request contract — it applies
`data/neg.json`, sets the Table 21 sampling params, and translates
friendly client field names to vLLM-Omni wire names before forwarding to :8000.

### Client contract — `POST /generate` (multipart form-data)

Clients send only creative intent. The gateway handles everything else.

| Field | Type | Default | Notes |
|---|---|---|---|
| `image` | file | one of | conditioning frame (PNG/JPEG/WebP) → **image-to-video** |
| `video` | file | one of | conditioning clip (MP4) → **video-to-video** (continuation) |
| `prompt` | string | required | prose brief; upsampler expands to structured JSON |
| `size` | string | `720x1280` | `WxH`; must be in `RESOLUTION_RATIO_DICT`. 400 if unsupported. |
| `frames` | int | `189` | frame count. Ceiling is **resolution-aware**: 400 at 256p/480p, 300 at 720p/768p |
| `steps` | int | `35` | `35` (NVIDIA model-card reference) or `50` (paper eval quality). Any other value → 400. |
| `sound` | bool | `true` | audio generation on/off |
| `upsample` | bool | `true` | expand prompt via Opus before sending to engine |
| `seed` | int | (random) | optional; gateway generates if omitted |
| `condition_seconds` | float | `0.2` | **V2V only.** How much of the clip's *end* conditions the render. 400 on the `image` path. |

#### Mode is selected by which file field you populate

**Exactly one of `image` / `video` is required** — sending both, or neither, is a
400. There is no mode flag, and that is deliberate: vLLM-Omni has no V2V field in
its wire protocol. It decodes `input_reference` (image decode first, video decode
as fallback) and branches on what it got — `is_v2v = video_tensor is not None`.
A boolean could therefore only *assert* the mode, never select it, so the
gateway mirrors the engine and dispatches on the media itself.

```bash
curl -F image=@still.png  -F prompt='…' localhost:8002/generate   # i2v
curl -F video=@clip.mp4   -F prompt='…' localhost:8002/generate   # v2v
```

V2V-specific rules:

- **`frames` must be of the form 4k+1** (189, 237, …). The WAN VAE folds 4 pixel
  frames into 1 latent frame; any other count makes the encoded conditioning
  latent disagree with the noise tensor and the engine raises
  `Cosmos3 V2V latent shape mismatch`. The gateway returns 400 up front and
  names the nearest valid counts. *(The same maths governs I2V, but that path is
  left unvalidated for now — no I2V request has ever been rejected for it.)*
- **`upsample` works**, using a continuation-specific template: the conditioning
  clip is ground truth for what has *already happened*, and your prompt is intent
  for what happens *next*. The reasoner is shown 5 stills sampled across the
  conditioning window (Opus cannot read video), so it sees direction and speed of
  motion rather than one pose.
- **The `duration` in the structured prompt is the *generated* length**, not the
  whole output — `(frames - condition_frames) / fps`. This follows NVIDIA's own
  V2V contract, where the Physics-IQ protocol conditions on 3 s, predicts 5 s, and
  pins `duration="0:05"`. Describing the total would ask the model to fit the
  future into a window that is partly already spent.
- **Conditioning comes from the END of the clip.** Post the previous clip whole —
  the gateway decodes it, keeps the final N frames, and forwards those. You do
  not need to pre-trim. This exists because `condition_video_keep: "last"` is
  dead over HTTP (BUG_003): the engine truncates to the first N frames at decode
  time, before the setting is read.
- **Source clips must be exactly 24 fps.** Rejected with 400 naming the actual
  rate. The engine decodes by frame count with no timestamp awareness, so any
  other rate is replayed as slow or fast motion with a discontinuity at the seam.
  Re-encode with `ffmpeg -r 24` first.
- **The clip must be at least as long as the conditioning window** (49 frames for
  `condition_seconds=2.0`). Rejected with 400. A shorter clip would be padded by
  repeating its final frame, which tells the model the scene has stopped moving —
  it then generates a frozen scene, with no error anywhere.
- **`condition_seconds` quantises upward.** The VAE folds 4 pixel frames into 1
  latent frame, so `2.0` s (48 frames) becomes a **49-frame** window. The response
  reports the real value in `condition_frames` — trust that, not your request.
  ⚠️ A client that pre-trims to exactly 2.000 s arrives **one frame short** and is
  rejected. Post the whole clip, or trim to ≥ 49 frames.
- The conditioning frames are **part of** `frames`, not additional to it, and
  come back as a VAE round-trip rather than your original pixels. There is no
  audio conditioning — audio under the recycled prefix is invented.

##### Chaining clips

The intended use: render clip 1 from a still (I2V), then condition clip 2 on
clip 1's final seconds instead of its final frame, so motion carries across the
seam rather than restarting from a frozen pose.

```bash
# clip 1 — unchanged, from a still
curl -F image=@opening.png -F prompt="$(cat script1.txt)" localhost:8002/generate

# clip 2 — post clip 1 whole; the gateway takes its last 2 s
curl -F video=@clip1.mp4 -F condition_seconds=2.0 \
     -F prompt="$(cat script2.txt)" localhost:8002/generate
```

Clip 2's first `condition_frames` frames are a VAE round-trip of clip 1's tail —
the same footage, slightly shifted in colour. **Discard them when concatenating**,
or every seam replays two seconds:

```
final = clip1 + clip2[condition_frames:] + clip3[condition_frames:] + …
```

#### What the gateway injects (clients never send these)

| Wire field | Value |
|---|---|
| `negative_prompt` | contents of `data/neg.json` (NVIDIA Appendix B.6) |
| `guidance_scale` | `6.0` (Table 21) |
| `flow_shift` | `10.0` (Table 21) |
| `fps` | `24` |
| `max_sequence_length` | `4096` |
| `extra_params` | `{"guardrails": false, "use_resolution_template": false, "use_duration_template": false}` |
| `sound_duration` | `frames / 24` (derived) |
| `seed` | random if not provided by client |

#### Gateway → vLLM-Omni field translation

| Client sends | vLLM-Omni wire name |
|---|---|
| `image` (file) | `input_reference` |
| `frames` | `num_frames` |
| `steps` | `num_inference_steps` |
| `sound` | `generate_sound` |

#### Response

Returns the upstream job JSON plus:
- `mode: "i2v" | "v2v"` — which conditioning path ran, derived from the file field supplied
- `condition_frames` / `generated_frames` — how the output splits. On V2V the first `condition_frames` are the recycled source tail; drop them when chaining. Both `null` on I2V (nothing to discard)
- `prompt_source: "upsampled" | "prose"` — whether Opus expanded the prompt
- `upsample_fallback_reason` — `null` when upsampled; otherwise `"disabled_by_request"`, `"no_api_key"`, `"refusal"`, `"invalid_json"`, or `"api_error: …"`
- `upsampler_output` — the exact structured prompt string the upsampler produced and the gateway sent to the engine, for provenance/viewing. `null` on the prose path (`prompt_source: "prose"`), including when an attempted upsample failed and fell back — the field means "what the upsampler produced," not "what ran"

These fields are also merged into `/jobs/{id}` polls (best-effort; in-memory, lost on gateway restart).

**HTTP 400** is returned (before any API tokens are spent) if: `size` is not in `RESOLUTION_RATIO_DICT`, the **generated** span falls outside `'2s'`–`'10s'`, `steps` is not 35 or 50, both or neither of `image`/`video` were supplied, `video` was supplied with a `frames` count that is not 4k+1, or `condition_seconds` consumes the whole output.

Note the duration ceiling is **NVIDIA's, not ours**: `data/upsampler_schema.json` (vendored) restricts `duration` to `'2s'`–`'10s'`, and `upsampler._ALLOWED_DURATIONS` mirrors it. Widening it would put an out-of-distribution value in the structured prompt.

#### Duration is measured over the generated span, not the whole output

On V2V, `duration` counts **`frames - condition_frames`**. This follows NVIDIA's own
V2V contract — the Physics-IQ protocol conditions on 3 s, predicts 5 s, and pins
`duration="0:05"`. It is also what makes a full 10 s of new video reachable inside
the vendored `'2s'`–`'10s'` enum:

| config | conditioning | generated | total | duration sent | where it fits |
|---|---|---|---|---|---|
| 2 s in → 10 s out | 49 (2.04 s) | 240 (**10.0 s**) | **289** | `'10s'` | 480p and 720p |
| 3 s in → 10 s out | 73 (3.04 s) | 240 (**10.0 s**) | **313** | `'10s'` | **480p only** |

Both totals are 4k+1. 313 exceeds the 300-frame 720p ceiling, so the longer
conditioning window is a 480p-only option. On I2V nothing changes — duration is
still measured over the total.

| Method | Path | Notes |
| GET | `/jobs/{id}` | upstream status with a **moving progress bar**: a gateway elapsed-time estimate (`progress_source: "estimate"`, `eta_s` = expected − elapsed) that climbs as the render runs, capped at 99; the log sidecar then pins it to 99 (`progress_source: "sidecar"`) once denoise finishes (the VAE/audio/encode tail), and it snaps to 100 on completion. Progress is `max(server, estimate)` so a future real server value would win |
| GET | `/jobs/{id}/content` | streams the MP4 |
| DELETE | `/jobs/{id}` | delete the job record. ⚠️ does NOT stop in-flight GPU work — vLLM-Omni aborts are bookkeeping only; an orphaned render runs to completion and blocks the queue |
| DELETE | `/jobs/{id}?hard=true` | **hard stop**: deletes the record AND, if this job is the active render, restarts the engine via the sidecar to actually reclaim the GPU. Costs ~3.5 min model reload and wipes all queued job records. Response: `{"hard": true, "engine_restarting": bool, "engine_down_confirmed": bool}` — the gateway waits (≤30 s) for the engine to actually go down before returning, so `engine_down_confirmed: true` means the subsequent `GET /health` → `cosmos: true` is a real ready signal (not the pre-restart container still answering). Poll `/health` until `cosmos: true` before resubmitting |
| GET | `/health` | `{"gateway": "ok", "cosmos": true}` |

Everything below documents the raw vLLM-Omni API behind the gateway —
needed for maintaining the gateway itself, not for clients.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/videos` | submit async job → returns job object with `id` |
| POST | `/v1/videos/sync` | generate and return raw video bytes in one call (blocks ~50 min at 50 steps — the async flow is almost always what you want) |
| GET | `/v1/videos` | list jobs (`{first_id, last_id, has_more, data: […]}`) |
| GET | `/v1/videos/{id}` | job status/metadata (see docs/responses.md) |
| GET | `/v1/videos/{id}/content` | download the MP4 |
| DELETE | `/v1/videos/{id}` | delete job |
| GET | `/health` | 200, empty body |
| POST | `/v1/omni/sleep`, `/v1/omni/wakeup` | release/restore GPU memory between jobs — **requires `--enable-sleep-mode` at startup (not currently enabled in our compose)**. Body: `{"stage_ids": [0], "level": 2}` |

The server also exposes `/v1/chat/completions`, `/v1/images/generations`,
`/v1/audio/*`, `/v1/video/chat/stream`, `/v1/realtime` etc. — unused by us.

## POST /v1/videos — multipart form-data fields

All values are strings (multipart). Image conditioning goes in the
`input_reference` **file** part.

### Fields we use in production

| Field | Type | Our value | Notes |
|---|---|---|---|
| `prompt` | string | (required) | |
| `negative_prompt` | string | contents of `data/neg.json` | server default is **empty** — always send ours |
| `size` | "WxH" | `720x1280` | server may snap to valid dims (real jobs come back `704x1280`); auto-calculated from input aspect ratio capped at 720·1280 area if omitted |
| `num_frames` | int | 5–300 | 189 ≈ 7.9 s |
| `fps` | int | `24` | |
| `num_inference_steps` | int | `50` (4 for smoke tests) | |
| `guidance_scale` | float | `6.0` | |
| `flow_shift` | float | `10.0` | |
| `generate_sound` | bool | `true` | ⚠️ NOT `enable_audio` |
| `sound_duration` | float | `num_frames / fps` | seconds |
| `seed` | int | random | |
| `extra_params` | JSON **string** | see below | |
| `input_reference` | file | the conditioning image | |

### extra_params (verified against pipeline_cosmos3.py)

```json
{"guardrails": false, "use_resolution_template": false, "use_duration_template": false}
```

- `guardrails` — toggles cosmos-guardrail text safety (pre) and video safety /
  face-blur (post) checks.
- `use_resolution_template` (default **true**) — appends
  `"This video is of {height}x{width} resolution."` to the prompt.
- `use_duration_template` (default **true**) — appends duration/fps text to the
  prompt. We disable both so the prompt stays exactly what we wrote and our
  explicit size/num_frames are honoured.

### Other available fields (unused by us, from OpenAPI)

`model`, `seconds`, `user`, `width`, `height` (alternative to `size`),
`guidance_scale_2`, `boundary_ratio`, `true_cfg_scale` (Wan-family params),
`image_reference` / `video_reference` (URL or base64 alternatives to the file
part), `lora`, and RIFE post-interpolation: `enable_frame_interpolation`,
`frame_interpolation_exp`, `frame_interpolation_scale`,
`frame_interpolation_model_path`.

## Job lifecycle

`queued` → `in_progress` → `completed` (then GET `…/content`), or
`failed` / `error` / `cancelled`.

### Progress: the server field is dead, and the logs only flush at the end

The `progress` field is **never updated during generation** (verified in
vllm-omni 0.21.0 source and upstream main, 2026-06-12: it defaults to 0 in
`protocol/videos.py:385` and is written once, to 100, at completion in
`api_server.py:2528-2540`; no flag or extra_params changes this).
`stage_durations` / `inference_time_s` / `peak_memory_mb` are likewise
completion-only. The `"seconds": "4"` in status payloads is an unused default
(ignored whenever `num_frames` is sent).

**There is no usable live per-step signal in the logs either.** tqdm renders
the denoise bar as a *single line* updated in place with `\r`, emitting no
newline until the loop ends. Docker captures that as **one log record,
timestamped at the bar's start**, and does not surface it to any log consumer
(`docker logs`, `--since`, or a streaming follower) until it is
newline-terminated — i.e. when denoise *finishes* (or the engine dies). So
mid-render every log reader sees nothing; at the end all the steps flush at
once. `PYTHONUNBUFFERED=1` does **not** change this — it governs Python's own
buffering, not docker's record framing. (Verified 2026-06-13: a real
`in_progress` job showed `24/50` in full `docker logs` while `--since 5m`
returned zero bar-lines.)

So the **progress sidecar** (`progress-sidecar/`, container
`cosmos3-progress`) cannot show smooth motion during a render. What it *is*
reliable for is that terminal flush: it reports the **final** step and the
`step==total → VAE/audio/encode tail` transition — a "denoise done, now
finishing" signal.

```
GET :8001/progress
{"active": true, "video_id": "video_gen_…", "step": 50, "total": 50,
 "percent": 100, "seconds_per_step": 12.5, "eta_s": 0.0, "age_s": 3.1}
```

`age_s` is wall-clock since the sidecar last *received* a bar line (not the
docker log timestamp, which is frozen at bar start); `video_id` is best-effort
(single-job server, from recent access logs).

A **moving** progress bar therefore comes from an elapsed-time estimate, not
the logs — implemented in the **gateway** (`/jobs/{id}`), with the sidecar kept
as the terminal "denoise done" override:

- `progress_source: "estimate"` — `min(99, elapsed/expected × 100)` where
  `elapsed = now − created_at` and `expected = denoise + tail`, both scaling
  with the job's pixel·frame volume `W·H·frames`:
  - `denoise = steps · 13.02 · (vol/vol_ref)^1.6`
  - `tail = 423 · (vol/vol_ref)` (VAE decode + audio + encode)
  - `vol_ref = 832·480·189`. Anchored on one fully-measured job (832×480×189,
    50 steps): sidecar caught **13.02 s/step** denoise, engine reported
    **1073.8 s** end-to-end → tail ≈ 423 s. The exponent 1.6 reproduces the
    measured **~46 s/step at 704×1280×189** and puts 720p at ~55 min
    end-to-end (inside the measured 50–57 min band). Constants live at the top
    of `gateway/server.py`; recalibrate by reading `seconds_per_step` from
    `:8001/progress` + `inference_time_s` from the final status.
  - `progress = max(server, estimate)`, monotonic, so a future real server
    value wins. `eta_s = expected − elapsed`.
  - Caveat: `created_at` is *submission* time. On this single-GPU box jobs run
    one at a time with ~0 queue wait, so it ≈ denoise start; a job queued
    behind another would over-count the wait (acceptable here).
- `progress_source: "sidecar"` — when the sidecar's bar (id-matched, fresh)
  reaches `step == total`, the gateway pins progress to **99** for the tail.
- On `completed`, the upstream `progress` is already 100.
