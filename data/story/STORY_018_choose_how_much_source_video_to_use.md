# STORY_018 — Choose how much of the source clip the model looks at

**Epic:** EPIC_001 — Continue an existing video clip
**Depends on:** STORY_017

As a pipeline operator, I want to say how many seconds of my source clip the
model should study before it starts inventing, so that it has enough motion
history to continue the action convincingly.

## Acceptance Criteria

- [ ] `POST /generate` accepts `condition_seconds` (float, default `0.2` ≈ the engine's 5-frame default)
- [ ] The gateway translates `condition_seconds` into `condition_frame_indexes_vision` and injects it into `extra_params`
- [ ] `condition_seconds=2.0` produces `condition_frame_indexes_vision = "0,1,…,12"` (49 pixel frames)
- [ ] The gateway **rejects with 400** any request whose uploaded clip contains fewer real frames than the conditioning window requires
- [ ] The gateway **rejects with 400** a source clip whose frame rate is not 24 fps, naming the actual rate
- [ ] `condition_seconds` is rejected if it would consume ≥ `frames` (nothing left to generate)
- [ ] The response reports `condition_frames` and `generated_frames` so clients can see the split
- [ ] `condition_seconds` on the I2V path returns 400 — it is meaningless without video
- [ ] `docs/api.md` documents the field, the 24 fps precondition, and the minimum-frames rule

## Technical Notes

**The translation.** Conditioning is addressed in *latent* frames; the VAE
compresses 4:1 temporally, so a latent index covers 4 pixel frames:

```python
pixel_frames  = round(condition_seconds * FPS)
max_index     = max(0, ceil((pixel_frames - 1) / 4))
indexes       = list(range(max_index + 1))          # contiguous from 0
actual_frames = max_index * 4 + 1                   # what the engine will use
```

For `condition_seconds=2.0`: `pixel_frames=48` → `max_index=12` →
`indexes=[0..12]` → `actual_frames=49` (2.0417 s). Report `actual_frames` back
as `condition_frames`, not the requested value — the engine works in quantised
steps of 4 and the client should see the truth.

Both the API layer and the pipeline layer accept a comma-separated string
(`_parse_video_condition_frame_indexes` at `api_server.py:2392` and
`_normalize_condition_frame_indexes_vision` at `pipeline_cosmos3.py:103` both
split on commas), so `"0,1,2,…,12"` is safe to send. A JSON list also works.

**Why the minimum-frames guard is the important part of this story.** The server
decodes at most `max(index)·4+1` frames from the upload. If the clip is *shorter*
than that, nothing errors: `_prepare_latents_v2v` pads the tensor by repeating
the final frame out to `num_frames`, and the conditioning indexes then land on
frozen repeats. The model is handed a clean, confident signal that says *the
scene has stopped moving* — and it faithfully continues a frozen scene. This is
the single most likely way to get a silently bad render, so the gateway must
count frames before submitting.

Counting requires decoding the upload. Use PyAV (already a serving dependency)
or `ffprobe`; read the frame count **and** the frame rate in the same pass,
since the 24 fps check needs it too.

**Why 24 fps is a hard requirement.** `_decode_video_bytes` walks
`container.decode(video=0)` and takes the first N frames, with no timestamp or
frame-rate awareness whatsoever. A 30 fps clip yields 30 frames per second of
wall-clock, so 49 frames is 1.63 s of action — which is then played back at 24
fps as slow motion, with a time-base discontinuity where the generated
continuation begins. Rejecting is correct: silently producing a subtly wrong
result is worse than making the client run one `ffmpeg -r 24`.

**Do not expose `condition_video_keep`.** It does not work over HTTP — the
server truncates to the first N frames at decode time, so the pipeline's "last"
selects the last N of N. See BUG_003. Clients wanting the tail of a longer clip
must trim before upload; say so in `docs/api.md`.

**Extra params assembly.** `EXTRA_PARAMS` is currently a frozen JSON string
constant in `server.py`. It now has to be built per-request on the V2V path.
Build it from a dict and serialise, keeping the I2V path emitting the exact same
string it does today.

## Testing Plan

**Unit** (required) — `gateway/tests/test_condition_window.py`:
- the translation table: 0.2 s→`[0,1]`, 1.0 s→`[0..6]`, 2.0 s→`[0..12]`, 3.0 s→`[0..18]`
- `condition_frames` is reported as the quantised value (49), not the requested (48)
- a 30-frame clip with `condition_seconds=2.0` → 400
- a 25 fps clip → 400 naming the rate
- `condition_seconds` ≥ available frames → 400
- `condition_seconds` with `image=` → 400
- the I2V `extra_params` string is unchanged from the frozen constant

**Contract** (required) — curl:
- `condition_seconds=2.0` → response reports `condition_frames: 49`
- a deliberately short clip → 400 with an actionable message
- confirm the forwarded `extra_params` carries the index string (assert via the
  gateway's request log, per STORY_010)

**Smoke** (required — conditioning changes what the engine denoises) — 832×480,
`steps=35`, `frames=189`, `condition_seconds=2.0`, a 24 fps clip of ≥49 frames.
Verify the first ~2 s reproduce the source and the continuation does **not**
freeze. A frozen output is the signature of the padding failure above. ~26 min.

## Estimated Complexity

**Medium.** The arithmetic is simple; decoding the upload to validate it is new
work for the gateway, and the failure mode being silent makes the guard
load-bearing.
