# BUG_007 — Trimmed Extend clips report 24.1 fps, so the gateway rejects them as the next source

**Status:** Resolved 2026-09-07
**Found:** 2026-09-07, STORY_031 E2E (`run_e3bd921556a7`, the first real 3-clip agent run)
**Affects:** `flow` (`trim_prefix`, STORY_026); every Extend chain longer than two clips, agent or manual

## Summary

The sidecar trims the 73-frame condition prefix off every Extend output with a
`select='gte(n,73)'` filter and re-encodes (STORY_026). The result has the right
240 frames, but its **stream duration is 239/24 s**: the muxer never learns the
last frame's duration, so `avg_frame_rate` becomes 240 ÷ (239/24) = **5760/239 ≈
24.100 fps**. The gateway reads exactly that field (`gateway/video.py`
`_stream_fps` → `stream.average_rate`) and its 24-fps guard rejects the clip when
it comes back as the *next* Extend's source:

```
cosmos3 gateway: {"detail":"source clip must be 24 fps, got 24.100 fps. The engine decodes
by frame count with no frame-rate awareness ... re-encode with `ffmpeg -r 24` first"}
```

So an agent run renders clip 1 (I2V) and clip 2 (V2V from clip 1, which was never
trimmed) and then **fails at clip 3**, the first clip whose source is a trimmed
file. The same happens to a manual Extend-of-an-Extend in the UI.

## Steps to reproduce

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate,duration,nb_frames \
  -of csv=p=0 ~/Documents/flow-media/flow-outputs/video_gen_8c95b6b36a404b22943f1472043e80d1.mp4
# 5760/239,9.958333,240        ← trimmed clip 2 of run_e3bd921556a7
ffprobe ... flow-outputs-raw/video_gen_8c95b6b36a404b22943f1472043e80d1.mp4
# 24/1,13.041667,313           ← its untouched raw
```

Then Extend from the trimmed clip: `POST :8002/generate` answers 400 with the
message above; the run JSON records `state: failed` at `clip_index: 2`.

## Expected vs actual

- **Expected:** a trimmed clip is a first-class 24 fps clip — 240 frames,
  exactly 10.000 s, `avg_frame_rate 24/1` — and chains indefinitely.
- **Actual:** 240 frames over 9.958 s, `avg_frame_rate 5760/239`; rejected as a
  source. Playback is unaffected (players use per-frame timestamps), which is why
  the clip itself looked fine in the picker.

## Root cause

`ffmpeg -vf select=...,setpts=PTS-STARTPTS` forwards frames with correct
timestamps but no trailing duration; the mp4 muxer therefore closes the stream at
the last frame's *start*. Measured with the container's ffmpeg 7.1.5:

| output options                  | avg_frame_rate | duration | frames |
|---------------------------------|----------------|----------|--------|
| current                         | 5760/239       | 9.958    | 240    |
| current + `-r 24`               | 24/1           | 10.000   | 240    |
| current + `-r 24 -fps_mode cfr` | 24/1           | 10.000   | 240    |
| `…,fps=24` in the filter        | 24/1           | 10.000   | 240    |

`-r 24` (the fix the gateway's own error message suggests) is the smallest change.

## Acceptance criteria

- [x] `trim_prefix` passes `-r <fps>` on the output and the argv unit test asserts it
- [x] A regression test trims a synthetic 24 fps clip with the **real** ffmpeg (host and the Docker test stage both have it) and asserts `avg_frame_rate == 24/1`, `nb_frames == source − condition_frames`, duration `== nb_frames/24`
- [x] `run_e3bd921556a7`'s clip 2 is re-trimmed from its kept raw, `ffprobe` shows `24/1`, and the run is resumed to `done` with a clean third clip

## Resolution

`trim_prefix` passes `-r <fps>`. Verified end to end on 2026-09-07: clip 2 was
re-trimmed from its kept raw (313 frames → 240 at `24/1`, 10.000 s), the run was
resumed, and **clip 3 rendered from that re-trimmed clip** — the exact hand-off
that used to fail — landing at `24/1`, 10.000 s, 240 frames. Evidence:
`docs/evidence/story-031-agent-run/05-run-final.json`.
