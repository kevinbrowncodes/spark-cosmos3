# Overnight 2026-09-07 — two 30-second scenes, unattended

Kevin asked at 20:33 for two 30 s clips to review in the morning. Both were rendered by the
agent (three 10 s clips each: one image-to-video, two Extends), supervised by
`supervisor.py`, and stitched into one file each.

| Scene | Run | Seed | Size | Title Gemma gave it | Output |
|---|---|---|---|---|---|
| 1 | `run_9b56240457f8` | shower photo (1376x768) | 832x480 | 🚿 Sculpted in the Rain 🌊 | `run_9b56240457f8_full.mp4`, 30.1 s |
| 2 | `run_8b6325e5c726` | alpine lake photo (1376x768) | 832x480 | 🏞️ Golden Hour Physique Display 🏔️ | `run_8b6325e5c726_full.mp4`, 30.1 s |

Every clip measured `24/1` fps; clip 1 of each is 241 frames, clips 2–3 are 240 frames trimmed
from 313-frame raws (BUG_007's fix, holding on a fresh run).

## What changed on the way

- **20:33** Both runs created at **1280x720** (the seeds are landscape; STORY_033's
  shape-from-seed picked the right orientation).
- **21:26** Scene 1 paused at the memory gate after clip 1 (BUG_010); the supervisor restarted
  the idle engine as designed. But clip 2 then failed: `frames must be of the form 4k+1 …
  got 300`. The gateway clamps 720p jobs to 300 frames and a 10 s Extend needs 313 — **BUG_014**.
  A 10-second Extend at 720p cannot pass this gateway; at 480p the ceiling is 400.
- **21:29** Both runs retired and re-created at **832x480**. The one 720p clip that rendered is
  kept as `video_gen_cbb60985cb8a4f32874908612555cba0.mp4`.
- **21:36 → 22:30** Scene 1: three clips, no pauses at 480p, stitched 22:35.
- **22:30** Scene 2 paused at 21.8 GiB (gate 22) while Gemma was still resident; the supervisor
  restarted the engine once. The executor's own retry then passed as memory cleared.
- **22:38 → 23:35** Scene 2: three clips, stitched 23:35. Supervisor exited clean.

## The second seed

The tennis-court image Kevin attached in chat never reached the box — a chat attachment is not
a file on disk, and no such image existed anywhere readable. The alpine lake photo he had
uploaded through the UI earlier that evening stood in. Recorded here so the substitution is
not mistaken for a wrong pick.

## Supervisor design notes (for BACKLOG_005)

`supervisor.py` is a working draft of what the executor should do itself: restart an idle
engine when the gate trips, wait for `:8000/health` **plus** a settle period before resuming
(resuming at +12 s failed earlier that day), treat a gateway 500 / connection error as
transient, fall back to 480p after repeated failures, and join the clips on completion
(BACKLOG_008). One flaw seen live: it restarts on *any* pause without first giving the
executor's own retry a tick, which cost one unnecessary 5-minute reload at 22:30.
