# STORY_020 — Allow ten full seconds of newly generated video

**Epic:** EPIC_001 — Continue an existing video clip
**Depends on:** STORY_017, STORY_018, STORY_019

As a pipeline operator, I want two seconds of source footage to yield a full ten
seconds of **new** video, so that the conditioning frames I supply do not eat
into the footage I actually asked for.

## Acceptance Criteria

- [ ] On the V2V path, the duration validated and sent to the upsampler is computed from **generated** frames, not total frames
- [ ] `frames=289` with `condition_seconds=2.0` is accepted and yields exactly 240 generated frames (10.0 s)
- [ ] The I2V path's duration accounting is **unchanged** — total frames remains correct there
- [ ] `data/upsampler_schema.json` is **not** modified; the `'2s'`–`'10s'` range still holds
- [ ] The frame ceiling is **resolution-aware**: 400 frames at 256p/480p, 300 at 720p — `frames` above the ceiling for the requested size returns 400
- [ ] At 480p, 3.0 s of conditioning plus a full 10 s of new video (313 frames) is accepted
- [ ] The progress estimate is within ~10% of actual on a 289-frame job
- [ ] `sound_duration` covers the full 289 frames (12.04 s), not just the generated span
- [ ] A 289-frame 720p V2V job completes end-to-end
- [ ] `docs/api.md` records the generated-frames duration rule and the recalibrated timing table

## Technical Notes

**The ceiling is NVIDIA's schema, not our validation.** `_ALLOWED_DURATIONS`
(`gateway/upsampler.py:158`) permits `'2s'`–`'10s'` because
`data/upsampler_schema.json` — vendored from NVIDIA in STORY_003 — says
`"duration": "must be one of: '2s','3s',…,'10s'"`. That is the JSON caption
format the model was trained on. Emitting `'12s'` would put an out-of-distribution
value into the structured prompt. **Do not widen the enum.**

**The resolution is accounting, not relaxation.** Per STORY_019, the V2V
upsampler's `duration` describes the continuation, not the total clip. So:

```
frames            = 289          (4·72+1)      12.0417 s total
condition_frames  =  49          (indexes 0..12)  2.0417 s
generated_frames  = 240                          10.0000 s   ← duration = '10s'
```

`'10s'` sits exactly at the top of the vendored range. The target is met with the
schema untouched — `_parse_size` simply needs the generated count on the V2V
path instead of the total.

`_parse_size(size, num_frames, fps)` currently does
`duration = f"{int(num_frames / fps)}s"`. Add an explicit conditioning-frames
argument defaulting to 0, so the I2V path keeps its current behaviour with no
change at the call site's semantics.

**Watch the `int()` truncation.** `int(289/24)` is 12 and `int(240/24)` is 10 —
both exact here, but the existing code truncates rather than rounds. Any
`condition_seconds` that leaves a non-multiple of 24 will silently floor. Assert
the intended value in tests rather than trusting the arithmetic.

**Budget verification** at 704×1280, 73 latent frames, 44×80 grid patched by 2 →
880 tokens per latent frame → **64,240 tokens** against the model's 74,000-token
training context (technical report Fig. 10, line 772). Roughly 13% headroom.
289 is also inside the engine's 300-frame 720p limit from the same figure. This
is the tightest configuration in the epic; do not extend further without
redoing this calculation.

**The progress estimate over-predicts, and the tail constant is why — measured.**
Two V2V runs at exactly the reference volume (832×480×189, 35 steps, sound on,
so `scale = 1`), the second with `seconds_per_step` captured from the sidecar:

| Run | `inference_time_s` | measured s/step | implied tail |
|---|---|---|---|
| STORY_017 smoke | 558.6 s | (not captured) | ~107 s |
| STORY_018 chain | **503.1 s** | **12.9** | **51.6 s** |

The gateway model predicts `35 · 13.02 + 423 = 878 s` for these jobs — a 57–75%
over-estimate.

**`_REF_S_PER_STEP` is right; `_REF_TAIL_S` is wrong.** The measured 12.9 s/step
all but matches the 13.02 anchor, which leaves the tail as the entire error:
~52 s measured against a 423 s constant, roughly **8× too high**. The 423 s
figure was never measured directly — it was derived by subtracting
`50 · 13.02` from a single 50-step job's 1073.8 s. Since the per-step anchor is
now confirmed, that subtraction cannot be reconciled with these runs; the
anchor job most likely included time that is not per-render tail (model load or
queue), or was not the volume it was recorded as.

Recalibration guidance:
- Set `_REF_TAIL_S` from measurement, not subtraction. The two runs bracket
  50–110 s at the reference volume; take more samples before fixing a value.
- Leave `_REF_S_PER_STEP` at 13.02 — independently confirmed at 12.9.
- `_VOLUME_EXP = 1.6` is still only validated by the 704×1280×189 ~46 s/step
  observation. The 289-frame 720p smoke in this story is the first real test of
  it at a third volume; capture `seconds_per_step` there too and check the
  exponent before trusting the estimate at the new length.

The constants in `gateway/server.py` were anchored on a single fully-measured
832×480×189 job and the measured ~46 s/step at 704×1280×189. A 289-frame job is a 1.53× volume
extrapolation along a curve with exponent 1.6 — the estimate is unlikely to hold.
Predicted at 35 steps: denoise ~55 min, tail ~24 min, **~80 min total**. Capture
the real numbers (`seconds_per_step` from `:8001/progress`, `inference_time_s`
from the final status) during the smoke run and refit before closing the story.

**Audio spans the whole clip.** `sound_duration` is `frames / FPS` and must stay
that way — 12.04 s, not 10.0 s. The engine generates audio for the full output
including the conditioning prefix. Per EPIC_001 known limitation #5, that prefix
audio is invented rather than taken from the source; splicing the original audio
back is client-side work.

**Cost gate.** An 80-minute 720p job is the most expensive single operation in
this repo. Validate the frame arithmetic at 480p (~26 min) first, and check
`free -h` shows ≥50 GiB before starting. Exit code 137 means OOM.

**The frame clamp is currently resolution-blind.** `server.py` does
`frames = max(5, min(300, frames))`, which applies the 720p ceiling everywhere.
The report's resolution table (Fig. 10, line 772) gives **400 frames at 256p and
480p, 300 at 720p**. That matters for conditioning length:

| conditioning | + 10 s new | total | 720p (≤300) | 480p (≤400) |
|---|---|---|---|---|
| 2.0 s (49 fr) | 240 fr | **289** | fits | fits |
| 3.0 s (73 fr) | 240 fr | **313** | **over by 13** | fits |

So at 720p, 2 s of conditioning is forced if a full 10 s of new video is wanted —
3 s would cap the continuation at 227 frames (9.46 s). At 480p there is no
conflict and 313 (4·78+1) is a valid count. Make the clamp read the ceiling from
the requested size rather than assuming 300.

**Why conditioning length is in scope here.** During the EPIC_001 A/B, two
scenarios failed on *state preservation*: dust established in the conditioning
window vanished, and a car drove through a rockfall that was blocking it. Cosmos3-Nano
scores **50.2** on Physics-IQ V2V (direct, no best-of-N reranking) — roughly half
the physical fidelity of real footage — so some failure is expected. But NVIDIA's
protocol conditions on **3 s**, not 2, and more motion history is exactly what
constrains physics. Whether the extra second earns its cost is measurable, and
480p is where it can be measured for free.

## Testing Plan

**Unit** (required) — `gateway/tests/test_generated_duration.py`:
- `_parse_size` with 289 frames / 49 conditioning / 24 fps → `'10s'`
- `_parse_size` with 289 frames / 0 conditioning → raises (12s exceeds the enum)
- the I2V path with 189 frames / 0 conditioning → `'7s'`, unchanged from today
- `frames=301` → 400; `frames=289` → accepted
- `sound_duration` for 289 frames is 12.0417, not 10.0
- the vendored schema file is unmodified (hash or literal assertion)

**Contract** (required) — curl:
- `frames=289 condition_seconds=2.0` returns 200 with
  `condition_frames: 49`, `generated_frames: 240`
- `upsampler_output` carries `duration: '10s'`
- `GET /jobs/{id}` progress climbs monotonically and `eta_s` is sane at
  submission

**Comparative round** (required — establishes whether conditioning length affects
physical fidelity): 12 scenarios at 480p, same structure as the EPIC_001 A/B —
same source clips, same seeds, blinded and balanced left/right — with the only
variable being `condition_seconds` **2.0 vs 3.0** at 313 frames. Score for
state preservation and object solidity specifically, since those are the failure
modes observed at 2 s. 24 renders, ~3.5 h. A null result keeps 2 s and settles the
720p trade-off; a clear win for 3 s means 720p must choose between conditioning
quality and a full 10 s of output.

**Smoke** (required — this is the story's entire point) — two runs:
1. 832×480, `steps=35`, `frames=289`, `condition_seconds=2.0` — validates the
   arithmetic cheaply (~26 min)
2. 704×1280, `steps=35`, `frames=289`, `condition_seconds=2.0` — the real target
   (~80 min). Record `seconds_per_step` and `inference_time_s`, refit the
   estimate constants, and confirm the output is 289 frames of which the first
   49 match the source.

Pre-flight for both: `free -h` ≥50 GiB, no active generation in
`docker logs cosmos3-api --since 10m | tail`.

## Estimated Complexity

**Medium.** The code change is small and surgical. The cost is the 80-minute
smoke run and the estimate refit, and the risk is that 64,240 tokens is the
closest this deployment has run to the training context window.
