# EPIC_001 — Continue an existing video clip

**Status:** In progress — STORY_017 done, 018–020 planned
**Stories:** STORY_017 → STORY_020
**Related bugs:** BUG_003

---

## Goal

Today the gateway can only start a video from a **still image** (I2V). Cosmos 3
also supports **video-to-video (V2V)**: condition on a few seconds of real
footage and generate a physically consistent continuation.

The target shape for this epic:

> Hand the gateway **2 seconds** of source video and get back **10 seconds of
> newly generated video** continuing it.

### How the pipeline actually uses this — multi-clip scripts

The consumer is `ogtv-studios/pipeline`, which renders a sequence of clips from
a sequence of scripts (`script1.txt` → clip 1, `script2.txt` → clip 2, …).

- **Clip 1 is unchanged.** The pipeline sends a **still image** and the gateway
  runs I2V exactly as it does today. This epic must not disturb that path.
- **Clip 2 onward is where V2V lands.** Today the seam between clips is carried
  by a single frame — clip 2 starts from the *last frame* of clip 1. With V2V,
  clip 2 instead conditions on the **last 2 seconds** of clip 1, so the model
  inherits velocity, trajectory, and motion history rather than a frozen pose.

Two consequences that shape the stories:

**The conditioning window is the END of the source clip, not the beginning.**
This is the opposite of what the engine does by default, and BUG_003 means the
`condition_video_keep: "last"` knob that exists for exactly this purpose does
not work over HTTP — the server truncates to the first N frames at decode time.
The gateway therefore has to trim the tail itself before forwarding (STORY_018).
This repo owns the request contract; a client that forgets to trim would get a
silently wrong render, conditioned on the wrong end of its own footage.

**The pipeline must discard the recycled prefix when concatenating.** Clip 2's
first 49 frames are a VAE round-trip of clip 1's last 49 frames — the same 2
seconds, slightly shifted in colour and detail. Concatenating naively would
replay 2 seconds at every seam. The joining logic is:

```
final = clip1 + clip2[condition_frames:] + clip3[condition_frames:] + …
```

which is why `/generate` reports `condition_frames` and `generated_frames`
(STORY_018). The splice itself is client-side work in `ogtv-studios/pipeline`,
not gateway work.

A useful side effect: because the recycled prefix is discarded anyway, *Known
limitation #5* (invented audio under the recycled video) costs nothing in
practice — those frames and their audio never reach the final cut.

## Why it is worth doing

V2V is not a marginal mode — on NVIDIA's own Physics-IQ benchmark it is
substantially more physically faithful than I2V, because the model sees motion
history rather than a frozen instant:

| Model | Mode | Direct | +WMReward BoN |
|---|---|---|---|
| Cosmos3-Super | V2V | 59.7 | 63.4 |
| **Cosmos3-Nano** (ours) | **V2V** | **50.2** | **57.7** |
| Cosmos3-Super | I2V | 43.8 | 48.9 |
| **Cosmos3-Nano** (ours) | **I2V** | **40.2** | **43.8** |

Source: `docs/cosmos-3-technical-report.md` Table 13 (line 1548).
**Nano in V2V (50.2) outscores Super in I2V (43.8).** Motion context buys more
physical fidelity than a bigger model does.

## Scope

**In scope** — the gateway accepting video input, selecting the V2V path,
controlling how much of the source clip conditions the generation, prompting
appropriately for continuation, and lifting the output-length ceiling.

**Out of scope** — video *transfer* (edge/depth/segmentation control video →
RGB). That is a different Cosmos 3 mode with its own system-prompt prefix; it
was introduced only in mid-training and has **no released specialised model**
(technical report Fig. 8, line 583). Not attempted here.

**Explicitly deferred to the client repo** — splicing the original source
pixels and audio back over the generated prefix (see *Known limitations* #4 and
#5). That is presentation work for `ogtv-studios/pipeline`, not gateway work.

---

## Shared technical constraints

Every story in this epic depends on these. Verified against the running engine
(`vllm/vllm-omni:cosmos3`) and `models--nvidia--Cosmos3-Nano` config on
2026-07-27.

### The engine dispatches on media type, not on a flag

There is **no V2V flag in the wire protocol.** `_decode_media_bytes`
(`vllm_omni/entrypoints/openai/video_api_utils.py`) attempts an image decode
first and falls back to a video decode; the pipeline then sets
`is_v2v = video_tensor is not None`. A boolean toggle could therefore only ever
*assert* the mode, never *cause* it.

**Consequence for our API design:** the gateway takes a separate `video` file
field. Which field is populated *is* the toggle. Exactly one of `image` /
`video` is required.

### Frame arithmetic

| Quantity | Formula | Constant |
|---|---|---|
| Latent frames | `T_lat = (num_frames - 1) // 4 + 1` | VAE temporal compression 4 |
| Conditioning pixel frames | `max(index) * 4 + 1` | `_condition_pixel_frame_count` |
| Latent grid | `H/16 × W/16`, then patched by 2 | `scale_factor_spatial: 16`, `latent_patch_size: 2` |

`num_frames` **must be of the form 4k+1.** `_prepare_latents_v2v` hard-raises
`"Cosmos3 V2V latent shape mismatch"` if the VAE-encoded conditioning latent
does not match the noise tensor shape. Our long-standing default of 189 is
4·47+1, which is why it has always worked.

### The target configuration

```
num_frames = 289          (4·72+1)          = 12.0417 s total
  conditioning  49 frames (indexes 0..12)   =  2.0417 s   ← the source clip
  generated    240 frames                   = 10.0000 s   ← the deliverable
```

Budget check at 704×1280 (the size the engine actually snaps 720x1280 to):

- Latent grid 44×80, patched by 2 → **880 tokens per latent frame**
- 73 latent frames × 880 = **64,240 tokens**, against the model's 74,000-token
  training context (technical report Fig. 10, line 772). Fits, with ~13% headroom.
- 289 frames is inside the engine's **300-frame limit at 720p** (same figure).
- For reference, today's 189-frame jobs use 42,240 tokens.

Estimated cost using the gateway's own calibrated model
(`gateway/server.py` constants), 35 steps:

| Size | Frames | Denoise | Tail | Total |
|---|---|---|---|---|
| 704×1280 | 189 (today) | ~28 min | ~16 min | **~44 min** |
| 704×1280 | 289 (target) | ~55 min | ~24 min | **~80 min** |
| 832×480 | 289 (smoke) | ~15 min | ~11 min | **~26 min** |

**Do first-pass validation at 480p.** A wrong 720p run costs 80 minutes.

### The 10-second ceiling is NVIDIA's, not ours

`_ALLOWED_DURATIONS` (`gateway/upsampler.py:158`) permits `'2s'`–`'10s'`, and it
is not an arbitrary gateway rule — it mirrors the **vendored NVIDIA upsampler
schema** (`data/upsampler_schema.json`): `"duration": "must be one of:
'2s','3s',…,'10s'"`. Emitting `'12s'` would put a value in the structured JSON
prompt that the model never saw in training.

**This resolves cleanly.** In the report's V2V upsampler contract (line 2349),
`duration` describes the **generated continuation**, not the total clip: the
Physics-IQ V2V protocol conditions on 3 s and predicts 5 s, and the prompt
template instructs `Copy exactly: duration="0:05"` — the 5 s prediction, not an
8 s total. `temporal_caption` is likewise defined as *"the future M:SS playback
timeline **after** the conditioning video."*

So on the V2V path the duration reported to the upsampler must be computed from
**generated** frames, not total frames:

```
duration = (num_frames - conditioning_frames) / fps
         = (289 - 49) / 24
         = 10.0 s                    ← inside the vendored 2s–10s enum
```

We hit the 10-seconds-of-new-video target **without widening NVIDIA's schema.**
This is the core insight of STORY_020.

---

## Stories

| # | Story | Delivers | Status |
|---|---|---|---|
| **017** | Continue an existing video clip instead of starting from a still | The `video` field, mode dispatch, forwarding, 4k+1 validation. Engine-default 5-frame conditioning, prose prompts only. Proves the path. | **Done** |
| **018** | Choose how much of the source clip the model looks at | `condition_seconds` → `condition_frame_indexes_vision`. Unlocks the 2-second target. | Planned |
| **019** | Write prompts that continue a scene rather than describe a still | The V2V upsampler contract — continuation semantics, not still-frame description. | Planned |
| **020** | Allow ten full seconds of newly generated video | Generated-frames duration accounting, the 289-frame configuration, estimate recalibration. | Planned |

Stories ship **in order, one at a time**, per CLAUDE.md §10.5. STORY_017 is
deliberately a thin vertical slice: it de-risks the entire mode at 480p in ~26
minutes before we invest in the conditioning maths or the prompt work.

## Known limitations (documented, not fixed by this epic)

1. **Source clips must be pre-resampled to 24 fps.** `_decode_video_bytes` takes
   the first N frames with no timestamp or frame-rate awareness. A 30 fps 2 s
   clip yields 60 frames; the first 49 are 1.63 s of action replayed at 24 fps —
   slow motion, plus a time-base discontinuity at the seam.
2. **The upload must contain at least as many real frames as the conditioning
   window requires.** Supply fewer and `_prepare_latents_v2v` pads by repeating
   the final frame, then conditions latent frames on frozen repeats. No error is
   raised — the model is simply told the scene freezes, and continues a frozen
   scene. STORY_018 adds a gateway-side guard.
3. **`condition_video_keep: "last"` does not work over HTTP** — see BUG_003.
4. **The conditioning frames are returned as a VAE round-trip**, not original
   pixels. Expect a small colour/detail shift across the seam.
5. **There is no audio conditioning.** The source clip's audio is not consumed,
   so the generated prefix carries *invented* audio underneath recycled video.

## Definition of Done

- [ ] `POST /generate` accepts a `video` file and runs V2V end-to-end
- [ ] 2 s of 24 fps source produces 10.0 s of newly generated video (289 frames)
- [ ] The structured prompt describes the continuation, not the source still
- [ ] Progress estimate is accurate to within ~10% at 289 frames
- [ ] `docs/api.md` documents the V2V contract and all five known limitations
- [ ] Existing I2V clients are unaffected — no change to the `image` path
