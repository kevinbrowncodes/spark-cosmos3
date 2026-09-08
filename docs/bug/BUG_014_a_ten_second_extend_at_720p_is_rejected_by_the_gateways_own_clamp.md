# BUG_014 — A 10-second Extend at 720p is rejected by the gateway's own frame clamp

**Status:** Open
**Found:** 2026-09-07 21:26, the first overnight 720p agent run (`run_3e1771520e2a`) failing at clip 2
**Affects:** `gateway/server.py` (`_FRAME_CEILINGS`), every video-to-video request at 720p/768p with 10 s of new video — agent Extends and manual ones alike

## Summary

The sidecar asks for `frames=313` for a 10 s Extend (73 conditioning frames + 240 new, already
4k+1 — STORY_026). The gateway then clamps to a per-resolution ceiling:

```python
_FRAME_CEILINGS = {"256": 400, "480": 400, "720": 300, "768": 300}
```

313 → **300**, which is not of the form 4k+1, and the gateway's own V2V validator rejects the
value it just produced:

```
frames must be of the form 4k+1 for video-to-video (the VAE compresses 4 pixel frames into
1 latent frame); got 300, nearest valid are 297 and 301
```

So at 720p a 10-second Extend is impossible through this gateway — not because the engine
cannot do it, but because the clamp lands on an invalid number and nothing tells the caller
the ceiling exists. At 480p the ceiling is 400, 313 passes untouched, and the same chain
works — which is why the 832x480 run earlier today rendered all three clips and the 1280x720
one died at clip 2.

## Steps to reproduce

```bash
# any 1280x720 clip as the source; ask the sidecar for Length 10 with a video reference
scripts/flow_agent.sh run <landscape.jpg> cosmos-3-i2v-helios-scene 2 --size 1280x720 --zero-shot
# clip 1 (image → video, 241 frames) renders; clip 2 (Extend, 313 requested) → 400 as above
```

## Expected vs actual

- **Expected:** either the clamp snaps to a valid count (297 at 720p, i.e. 9.33 s of new
  video) and the response says how much was actually rendered, or the ceiling is advertised
  so the sidecar never asks for more than it can get.
- **Actual:** the clamp produces 300, the validator refuses 300, the run fails after the
  first clip — 40 minutes of GPU for one clip and no scene.

## Root cause

Two halves:

1. `server.py` clamps *before* validating and clamps to a number that is not itself valid
   for V2V. `min(frames, ceiling)` needs to become "the largest 4k+1 not above the ceiling"
   when a video is conditioning.
2. The ceiling is invisible to clients. The sidecar's `frames_for()` and the UI's Length
   control (5/8/10 s) have no idea that at 720p a video reference caps at 9.33 s. Length 10
   is offered, accepted at run creation, and fails an hour later.

## What tonight did about it

The two overnight runs were re-created at `832x480` (landscape, ceiling 400) so the scenes
exist in the morning; the 720p clip 1 that did render is kept as
`video_gen_cbb60985cb8a4f32874908612555cba0.mp4`.

## Acceptance criteria

- [ ] The gateway's clamp yields a valid V2V frame count (largest 4k+1 ≤ ceiling) and the job
      reports the frames actually rendered — covered by a gateway unit test at each ceiling
- [ ] The sidecar's `capabilities()` exposes the per-size frame ceiling, or Length options
      that cannot be honoured at the chosen size for a video reference are not offered — a
      story, because it changes what the UI shows
- [ ] `scripts/flow_agent.sh run … --size 1280x720` with a video reference either renders
      the longest valid Extend or refuses up front with the real limit, never a 400 at clip 2
