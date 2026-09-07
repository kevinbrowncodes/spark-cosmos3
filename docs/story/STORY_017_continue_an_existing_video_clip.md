# STORY_017 — Continue an existing video clip instead of starting from a still

**Epic:** EPIC_001 — Continue an existing video clip

As a pipeline operator, I want to hand the gateway a short video clip instead of
a still image, so that the model continues the motion already happening in my
footage rather than inventing movement from a frozen frame.

## Acceptance Criteria

- [x] `POST /generate` accepts a `video` file field (MP4) in addition to the existing `image` field
- [x] Exactly one of `image` / `video` is required — supplying both returns **400**, supplying neither returns **400**
- [x] When `video` is supplied, the gateway forwards the bytes as `input_reference` with the correct media type and the engine runs the V2V path
- [x] When `image` is supplied, behaviour is **byte-for-byte unchanged** from today — existing pipeline clients need no modification
- [x] `frames` is validated to be of the form **4k+1**; anything else returns 400 with a message naming the nearest valid values
- [x] The `/generate` response and `/jobs/{id}` polls report `mode: "i2v" | "v2v"`
- [x] A 480p V2V generation completes end-to-end and the output visibly continues the source clip's motion
- [x] `docs/api.md` documents the `video` field and the mode-dispatch rule

## Technical Notes

**This story deliberately does not touch the conditioning maths.** It uses the
engine's default `condition_frame_indexes_vision = (0, 1)` — 5 pixel frames,
matching the `T_cond = 2` recipe used in Cosmos 3 pre-training (technical report
line 791). Widening that window to 2 seconds is STORY_018. Keeping them separate
means we discover any surprise in the V2V path for the cost of a ~26 minute 480p
run rather than an 80 minute one.

**Prompting stays on the prose path for this story.** The existing I2V upsampler
prompt describes a *starting frame*; pointing it at a video would produce a
still-frame description of frame 0. Until STORY_019 lands, `upsample` must be
forced to `false` on the V2V path, and the response must report
`upsample_fallback_reason: "v2v_not_supported"` so the behaviour is visible to
clients rather than silent.

**Mode dispatch, not a toggle.** The engine has no V2V flag — it decodes the
media and branches on the result (`is_v2v = video_tensor is not None`,
`pipeline_cosmos3.py:1812`). The gateway must mirror that: the populated field
selects the mode. Do **not** add a boolean; it could only assert what the bytes
already determine.

**Changes in `gateway/server.py`:**

```python
image: UploadFile | None = File(None),
video: UploadFile | None = File(None),
```

- 400 on `bool(image) == bool(video)` (covers both-supplied and neither-supplied)
- `media = image or video`; `mode = "i2v" if image else "v2v"`
- Media type: `video.content_type or "video/mp4"` (the engine sniffs by decoding
  and ignores the declared type, but sending the truth costs nothing)
- The `files={"input_reference": …}` part is unchanged in shape — only its
  contents differ
- Add `mode` to the `_JOB_META` record so `/jobs/{id}` can echo it

**The 4k+1 rule.** `_prepare_latents_v2v` raises
`"Cosmos3 V2V latent shape mismatch"` when the encoded conditioning latent and
the noise tensor disagree, which happens whenever `num_frames` is not 4k+1. The
existing default of 189 (4·47+1) has always satisfied this by accident. Validate
in the gateway so the client gets a 400 rather than a 500 an hour later.

**Negative prompt — deliberate deviation, recorded here.** The engine defaults
V2V to the *short* negative prompt on purpose; the comment at
`pipeline_cosmos3.py:78` explains that the verbose video negative "biases the
model away from legitimate low-motion / low-light content carried over from the
source clip." Our gateway unconditionally injects the long `data/neg.json`.
**For this story we keep injecting `data/neg.json`** so V2V and I2V stay
comparable and only one variable changes. If the 480p smoke output shows the
model fighting the source clip's low-motion or low-light content, raise a
follow-up story — do not quietly change it here.

## Testing Plan

**Unit** (required) — `gateway/tests/test_v2v_dispatch.py`:
- both fields supplied → 400; neither supplied → 400
- `image` only → `mode == "i2v"`, media type preserved
- `video` only → `mode == "v2v"`, media type `video/mp4`
- `frames` of 189, 289 accepted; 190, 240, 200 rejected with 400
- `upsample=true` on the V2V path is forced off and reports
  `upsample_fallback_reason: "v2v_not_supported"`

**Contract** (required) — curl against the running gateway:
- `POST /generate video=@clip.mp4` returns 200 with `mode: "v2v"`
- `POST /generate image=@still.png` returns a response **identical in shape** to
  the pre-story baseline (regression guard for existing clients)
- `GET /jobs/{id}` echoes `mode`

**Smoke** (required — the generation path changes) — 832×480, `steps=35`,
`frames=189`, a 24 fps source clip of at least 5 frames. Verify: the job
completes, the opening frames match the source, and motion continues past the
seam rather than restarting. Budget ~26 minutes.

Pre-flight: `free -h` must show ≥50 GiB available, and
`docker logs cosmos3-api --since 10m | tail` must show no active generation.

## Estimated Complexity

**Medium.** The gateway change is small and well-understood; the cost is in the
smoke run and in confirming the engine's V2V path behaves on our hardware.
