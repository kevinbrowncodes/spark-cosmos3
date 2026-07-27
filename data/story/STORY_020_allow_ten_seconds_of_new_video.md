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
- [ ] `frames` above the engine's 300-frame 720p limit returns 400
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

**The progress estimate needs recalibrating.** The constants in
`gateway/server.py` were anchored on a single fully-measured 832×480×189 job and
the measured ~46 s/step at 704×1280×189. A 289-frame job is a 1.53× volume
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
