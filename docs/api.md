# Cosmos 3 video API reference

Extracted from this server's own `/openapi.json` and the installed
`vllm_omni` source (image `vllm/vllm-omni:cosmos3`), 2026-06-12. The upstream
docs are thinner than this — the server is the source of truth.

## The gateway (:8002) — what clients should actually call

Clients should not talk to vLLM-Omni directly. The gateway (`gateway/`,
container `cosmos3-gateway`) owns the request contract — it applies
`data/neg.json`, appends `data/audio.txt` to the prompt when sound is on
(unless the prompt already has an `AUDIO:` section), sets the Table 21
sampling params and correct field names, and forwards to :8000.

| Method | Path | Notes |
|---|---|---|
| POST | `/generate` | multipart: `input_reference` (file), `prompt`; optional `size` (default 720x1280), `num_frames` (default 189, clamped 5–300), `num_inference_steps` (default 50), `generate_sound` (default true), `seed`, `upsample` (default true). Returns the upstream job JSON (incl. the final assembled `prompt`) plus `prompt_source: "upsampled" \| "prose"`. |
| GET | `/jobs/{id}` | upstream status with **real progress merged from the sidecar** when fresh + id-matched (`progress_source: "sidecar"`, `eta_s`); holds at 99 during the VAE/audio/encode tail |
| GET | `/jobs/{id}/content` | streams the MP4 |
| DELETE | `/jobs/{id}` | passthrough delete/cancel |
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

### Progress: the server field is dead — use the sidecar

The `progress` field is **never updated during generation** (verified in
vllm-omni 0.21.0 source and upstream main, 2026-06-12: it defaults to 0 in
`protocol/videos.py:385` and is written once, to 100, at completion in
`api_server.py:2528-2540`; no flag or extra_params changes this).
`stage_durations` / `inference_time_s` / `peak_memory_mb` are likewise
completion-only. The `"seconds": "4"` in status payloads is an unused default
(ignored whenever `num_frames` is sent).

Real per-step progress is served by our **progress sidecar**
(`progress-sidecar/`, container `cosmos3-progress`), which parses the tqdm
denoise bar from the cosmos3-api logs:

```
GET :8001/progress
{"active": true, "video_id": "video_gen_…", "step": 12, "total": 50,
 "percent": 24, "seconds_per_step": 46.1, "eta_s": 1752.2, "age_s": 3.1}
```

Semantics: `active` = denoise running and data fresh (<180 s); `step==total`
with `active: false` means the job is in the VAE/audio/encode tail (minutes);
`video_id` is best-effort (single-job server, taken from recent access logs).

Measured step times: **~46 s/step at 704×1280×189f**, **~14.4 s/step at
480×832×190f** (≈3.2× faster; 480p jobs complete in ~13 min end-to-end).
