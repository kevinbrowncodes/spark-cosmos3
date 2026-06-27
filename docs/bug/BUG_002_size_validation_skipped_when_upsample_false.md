# BUG 002 — Size/duration validation skipped when upsample=false

**Status:** Resolved

## Summary

Unsupported sizes (e.g. `1920x1080`) and out-of-range durations pass through to vLLM-Omni
without a 400 when `upsample=false`. The engine queues the job silently.

## Steps to Reproduce

```bash
curl -X POST localhost:8002/generate \
  -F "input_reference=@seed.jpg" \
  -F "prompt=test" \
  -F "size=1920x1080" \
  -F "upsample=false"
# → 200, job queued — should be 400
```

## Expected vs Actual Behaviour

**Expected:** HTTP 400 with a clear message on any unsupported size or out-of-range duration,
regardless of the `upsample` flag.
**Actual:** Validation only fires when `upsample=true` because `_parse_size` lives inside
`upsampler.upsample()`. With `upsample=false` the call is skipped entirely.

## Root Cause

Story 7 implemented `_parse_size` inside the upsampler path. There was no unconditional
validation step in `server.py`'s `generate()` endpoint.

## Acceptance Criteria

- [x] `generate()` calls `upsampler._parse_size(size, num_frames, FPS)` unconditionally before
      any upsampler or engine logic; raises HTTP 400 on ValueError.
- [x] `curl … size=1920x1080 upsample=false` → 400, not 200.
- [x] `curl … size=720x1280 num_frames=300 upsample=false` → 400, not 200.
- [x] Valid inputs with `upsample=false` still work normally.

## Resolution

Added unconditional size/duration validation at the top of `generate()` in `server.py`,
before the upsampler block. Uses `upsampler._parse_size()` as the single source of truth
for both the size lookup and the duration range check.
