# BUG_012 — The agent renders portrait seeds into a landscape frame, so the video comes out squashed

**Status:** Resolved 2026-09-07 by STORY_033
**Found:** 2026-09-07, watching `run_e3bd921556a7`'s joined output — "it's all smooshed"
**Affects:** `flow/runs.py` `DEFAULT_VALUES`; every agent run whose seed is not 16:9, which is every phone photo

## Summary

The agent hardcodes `size: "832x480"` — landscape 16:9 — for every run, no matter what the
seed looks like and regardless of what the gateway says its default is. Seeded with a
portrait phone photo, the engine conditions on that image as the first frame and rescales it
into the wide frame, so the whole clip is vertically compressed: heads are short and wide,
bodies are stretched sideways. The pixels are wrong; no player setting corrects it.

The gateway's own default is `720x1280` (portrait), which the Flow UI uses and which renders
correctly — the STORY_025 clip from the same box on the same day is properly proportioned.
The agent is the only path that picks a landscape frame.

## Steps to reproduce

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 \
  ~/Documents/cosmos-media/input_cap_guy.jpg                      # 768,1376  (portrait)
scripts/flow_agent.sh run ~/Documents/cosmos-media/input_cap_guy.jpg example-forecast-scene 1
ffprobe … the resulting clip                                       # 832,480   (landscape)
```

## Expected vs actual

- **Expected:** a portrait seed produces a portrait clip; the agent follows the gateway's
  default, or better, the seed's own shape.
- **Actual:** always `832x480`, so anything but a 16:9 seed is distorted.

## Root cause

`flow/runs.py`:

```python
DEFAULT_VALUES = {"size": "832x480", "length": 10, ...}
```

A constant chosen for cheap 480p test renders. Note the gateway offers `480x832` — the same
cost, the right way up — so even the "cheap" choice was the wrong one of the pair. Nothing in
`create()` consults `capabilities()` for the size default, though it already calls
`capabilities()` for normalisation and already holds the seed's path.

## Evidence the distortion is a plain linear squash

Frame 0 of clip 1, rescaled back to the seed's 768x1376, measured against the seed itself:

| comparison | PSNR |
|---|---|
| stretched back to the seed's shape | **29.40 dB** |
| letterboxed, aspect preserved | 8.75 dB |

So the content was squeezed, not recomposed — which is why an existing clip can be
un-squashed after the fact, at the cost of vertical sharpness (only 480 lines were rendered).

## Acceptance criteria

- [x] A run seeded with a portrait image renders portrait; one seeded with a landscape image renders landscape
- [x] ~~An explicit `--size` still wins over the automatic choice~~ — **reversed while implementing**: the Flow UI always sends a size, so honouring it would have left two landscape runs in a portrait frame. The request now sets the resolution and the seed sets the shape; a size the gateway does not offer is still rejected
- [x] The agent no longer carries a hardcoded size constant
- [x] Implemented under STORY_033, which this ticket blocks

## Resolution

STORY_033. Verified on the box without a render: the real portrait seed asked for at
`720x1280` records `720x1280`, and Kevin's landscape seed asked for at the same size records
`1280x720` — same 921,600 pixels, right way up. His two in-flight runs were corrected in
place before they reached the GPU. Evidence: `docs/evidence/story-033-seed-shape/`.
