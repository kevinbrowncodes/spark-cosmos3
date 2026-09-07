# BUG_009 — A queued run says "Caching clip n" when nothing is being cached

**Status:** Resolved 2026-09-07 (the container shows the new label after its next deploy)
**Found:** 2026-09-07, resuming `run_e3bd921556a7` after BUG_007 (`resume` → `queued | Caching clip 2`)
**Affects:** `flow/runs.py` `step_label` (STORY_030); shown in the CLI `watch`/`show` output and the Flow UI's run step

## Summary

`step_label` renders a `queued` run with `clip_index > 0` as **"Caching clip n"**.
The label was meant for the gap between a clip finishing and the next one being
submitted, but the sidecar caches a finished clip *inside* the poll that sees
`done` — by the time the run is `queued` the cache is already written. So the
label is never true, and after `resume` (which re-queues the clip that failed
or paused) it is actively misleading: a run waiting to render clip 3 reports
"Caching clip 2".

## Steps to reproduce

```bash
scripts/flow_agent.sh resume run_e3bd921556a7      # failed at clip 3
scripts/flow_agent.sh show run_e3bd921556a7        # queued  Caching clip 2
```

## Expected vs actual

- **Expected:** `Queued clip 3 of 3` (and `Queued clip 1 of 3` before the first clip).
- **Actual:** `Caching clip 2`.

## Root cause

`step_label`: `return "Queued" if n == 0 else f"Caching clip {n}"`.

## Acceptance criteria

- [x] A queued run reads `Queued clip {n+1} of {total}` for every `clip_index`; unit test covers `n == 0`, a mid-run queue, and a post-resume queue
- [x] The CLI `show` for a resumed run prints the new label (the running container picks it up at the next deploy)

## Resolution

`step_label` returns `Queued clip {n+1} of {total}` for every queued run (unit-tested for the
first, a mid-run, and a post-resume queue). `step` is persisted in the run JSON at save time, so an
already-queued run keeps its old label until its next state change — `run_e3bd921556a7`, queued
before the fix, still shows `Caching clip 2` and cannot be re-resumed (409) to refresh it. Verified
once that run paused at the memory gate: `POST /agent/runs/run_e3bd921556a7/resume` on the host-run
sidecar → `queued | Queued clip 3 of 3`, and `show` prints the same.
