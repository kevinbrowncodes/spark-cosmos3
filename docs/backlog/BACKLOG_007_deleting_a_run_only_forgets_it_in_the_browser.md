# BACKLOG_007 — Deleting a run only forgets it in the browser

**Priority:** Low — harmless today, but the records accumulate and confuse the next person
**Source:** 2026-09-07, two runs deleted from the UI were still on the backend at `review`

## Summary

The Flow UI's delete on a batch removes it from browser storage and writes a tombstone so it
does not come back. The run itself is untouched: there is no `DELETE /agent/runs/{id}`, so the
JSON record stays in `FLOW_MEDIA_DIR/flow-runs/` forever. A run deleted while waiting for
review sits there indefinitely — it will never render, because it needs an approval that can no
longer be given from any UI that has forgotten it.

The copy on the batch is honest about the render ("Removing this batch does not stop the
render"), but it does not say the run outlives the batch, and for a `review` run there is no
render to stop in the first place.

## User impact

Low. Orphaned records show up in `scripts/flow_agent.sh list` and in `GET /agent/runs`, so
anyone reading the backend sees runs the user believes are gone. They also keep their uploads
alive by reference. Nothing renders and nothing breaks.

## Rough scope

1. **A delete endpoint.** `DELETE /agent/runs/{id}`, refusing while `rendering` (the engine job
   would be orphaned) or deleting and letting the existing "removing does not stop the render"
   rule stand. The UI's delete calls it when the batch has a `runId`.
2. **A reaper.** Drop `review`/`failed`/`paused` records older than N days on startup. No API
   change, but it deletes things nobody asked it to.
3. **Leave it.** Say plainly in the delete copy that the run record stays, and let
   `flow_agent.sh` be the way to clean up.

## Dependencies

- Option 1 needs the flow protocol to carry the endpoint, so it belongs upstream (BACKLOG_003's
  promotion path) rather than being bolted onto this repo's mirror only

## Open questions

- Should deleting a run also delete the clips it rendered? Almost certainly not — Kevin's
  standing rule is that clips survive project deletion (STORY_028) — but it should be stated.
