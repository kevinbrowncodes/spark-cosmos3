# BACKLOG_008 — A finished run hands you the whole scene as one file

**Priority:** High — it is the thing the chaining exists to produce
**Source:** 2026-09-07, "where is link to full extended video?" — there was none

## Summary

An agent run renders N clips, each an Extend of the last, and stores them as N separate
files. Nothing joins them. The user of a three-clip run gets three downloads and a stitching
job; the 30-second scene the run was for does not exist anywhere until someone runs ffmpeg by
hand (done twice today: `run_e3bd921556a7_full.mp4`, and the overnight supervisor's
`<run>_full.mp4`).

## User impact

The run's purpose is one continuous video. Without the join the UI shows three tiles that
happen to be adjacent, the panel says Done, and the deliverable is still missing. First
reaction on seeing this was to open the wrong clip and assume the chain had not worked.

## Rough scope

1. **Join on completion, in the executor.** When the last clip lands, concatenate the served
   clips (already trimmed to exactly 10.000 s each — BUG_007) into `flow-outputs/<run>_full.mp4`
   with the concat demuxer and a re-encode, record it on the run as `media_id`, and have the
   protocol mirror expose it so the UI can show a single "scene" tile above the three clips.
   The supervisor script from 2026-09-07 is a working draft of the ffmpeg half.
2. **Stream copy instead of re-encode.** The clips share codec and parameters, so `-c copy`
   would be instant — but the earlier 24.1 fps trim bug lived exactly in how mp4 durations are
   written, so a re-encode with `-r 24` is the safer default until a stream-copy join is
   measured with the same ffprobe checks BUG_007 used.
3. **Where it shows.** The run record needs a field; the UI needs a tile; `flow_agent.sh show`
   should print the path. The UI half is upstream (flow, EPIC-003) — BACKLOG_003's promotion
   path again.

## Dependencies

- BUG_007 (trimmed clips are exact 24 fps, which is what makes a clean join possible)
- Upstream: a `scene` or `output` field on the protocol's `Run` model, and a tile for it

## Open questions

- Audio at the seams: the clips carry their own ambient audio; is a crossfade wanted, or is a
  hard cut at each 10 s boundary acceptable? Today's hand-made joins use hard cuts.
- Should the join also produce the un-squashed variant when the run predates STORY_033? No —
  that was a one-off repair, and new runs render the right shape.
