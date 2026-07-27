# BUG_003 — `condition_video_keep: "last"` is silently ignored over HTTP

**Status:** Open (upstream defect — documented, worked around client-side)
**Component:** `vllm/vllm-omni:cosmos3` engine, not our gateway
**Related:** EPIC_001, STORY_018

## Summary

The Cosmos 3 pipeline exposes `condition_video_keep` with values `"first"` and
`"last"`, intended to choose whether V2V conditions on the **beginning** or the
**end** of an uploaded clip. Over the HTTP API, `"last"` is indistinguishable
from `"first"` — the engine has already discarded the tail of the upload before
the setting is ever consulted.

No error is raised. The caller gets a valid render conditioned on the wrong part
of their footage.

## Steps to Reproduce

1. Take a 10-second, 24 fps clip (240 frames) whose opening and closing seconds
   differ visibly.
2. `POST /v1/videos` with the clip as `input_reference` and
   `extra_params = {"condition_video_keep": "last", "condition_frame_indexes_vision": "0,1"}`
3. Compare the opening frames of the output against the source.

## Expected vs Actual Behaviour

**Expected:** the generated video continues from the clip's final seconds.

**Actual:** it continues from the clip's opening seconds, identically to
`"first"`.

## Root Cause

Two truncation steps run in the wrong order, in different modules.

**First**, at decode time, the server stops reading after `max_frames`
(`vllm_omni/entrypoints/openai/video_api_utils.py`, `_decode_video_bytes`):

```python
for frame in container.decode(video=0):
    frames.append(frame.to_image().convert("RGB"))
    if max_frames is not None and len(frames) >= max_frames:
        break
```

`max_frames` comes from `_reference_video_frame_limit` (`api_server.py:2408`),
which returns `max(condition_frame_indexes_vision)·4+1` — 5 by default. The
remaining 235 frames of the example are never decoded.

**Second**, the pipeline selects from that already-truncated list
(`pipeline_cosmos3.py:278`):

```python
def _select_video_frames(frames, max_frames, keep):
    if keep == "last":
        return frames[-max_frames:]
    return frames[:max_frames]
```

Because the list handed in is already exactly `max_frames` long, `frames[-5:]`
and `frames[:5]` return the same five frames. The `keep` parameter is dead on
this path. It would function only for an in-process caller that bypasses the
HTTP decode step.

## Acceptance Criteria

- [x] Root cause identified and recorded
- [ ] `docs/api.md` states that `condition_video_keep` has no effect over HTTP
- [ ] STORY_018 does **not** expose `condition_video_keep` as a gateway field
- [ ] STORY_018 works around it **gateway-side** by trimming the upload to its
      final N frames before forwarding, so callers post whole clips
- [ ] `docs/api.md` documents the tail-trimming behaviour and why it exists
- [ ] Re-check on the next engine image bump; if fixed upstream, promote to a
      story for exposing the field properly

## Notes

Not worth patching locally — it lives in the upstream engine image, which this
repo deliberately runs unmodified (CLAUDE.md §5). Trimming before the bytes are
forwarded is equivalent in effect and costs a decode of ~49 frames.

**This defect is directly on the critical path for EPIC_001.** The pipeline's
whole use case is conditioning clip 2 on the *final* 2 seconds of clip 1, which
is precisely what `condition_video_keep: "last"` was meant to do. STORY_018
therefore does the trimming in the gateway rather than exposing the broken knob
or pushing the work onto callers.
