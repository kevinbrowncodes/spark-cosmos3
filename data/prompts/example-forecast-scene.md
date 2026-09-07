---
name: example-forecast-scene
description: >-
  A neutral example skill that ships with the repo so a fresh clone can plan a
  scene before Kevin's own skills are copied in. Forecasts the most plausible
  continuation of the seed image as {{COUNT}} ten-second clips written as timed
  motion beats.
---
# Example — plausible continuation, timed beats

> **THIS RUN WRITES EXACTLY {{COUNT}} CLIP(S).** Output exactly {{COUNT}} separate
> `<<<SCRIPT n>>>` blocks, one per clip — no more, no fewer. Count them before you finish.

You write MOTION INTENT for image-to-video clips. Read the attached seed image
and predict the most plausible, physically grounded continuation of the frozen
instant — what genuinely happens next if the moment is unpaused. Each clip is
exactly 10 seconds. Clip 1 continues the seed image; each later clip continues
from where the previous clip settled, so end every clip on a settled, in-focus
moment (for a person: a clear, steady pose, face visible, eyes open).

Write each clip as three timed beats covering 0:00–0:10:

- `[0:00-0:04]` the immediate continuation of what the frame already implies
- `[0:04-0:08]` the main development — something actually happens
- `[0:08-0:10]` the motion eases to a stable pause

Then, on their own lines: the camera stays completely fixed (no pan, tilt or
zoom); if a person is present, the mouth stays closed and still; ambient
environmental sound only, no voice or speech.

Describe only what moves, in what order, and when. Do not describe how the
subject, clothing, setting or lighting look — the image already carries that.
Present tense, concrete physical actions, cause before effect, the subject's
own left and right. Keep every action inside the existing framing and within
a real body's comfortable range.

## Output

Emit everything inline, wrapped in these exact markers and nothing else:

```
<<<SCRIPT 1>>>
…three timed beats + the constraint lines for clip 1…
<<<END SCRIPT>>>
```

…one block per clip, `<<<SCRIPT 1>>>` through `<<<SCRIPT {{COUNT}}>>>`, in order. Then:

```
<<<TITLES>>>
one short title per line, strongest first, ten lines, each starting with an emoji
<<<END TITLES>>>
<<<SUMMARY>>>
a heading naming the piece and its runtime ({{COUNT}} × 10 s), then a table
Stage | Clip | What happens, one row per clip, then two sentences on the through-line
<<<END SUMMARY>>>
```

Final check: there must be exactly {{COUNT}} `<<<SCRIPT n>>>` blocks.
