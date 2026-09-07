# BACKLOG_002 — Flow UI: cancel a render, show an ETA, one-click Extend

**Status:** Open
**Priority:** Medium — quality-of-life once EPIC_002 has landed
**Where the work is:** `kevinbrowncodes/flow` (protocol + UI), **not this repo**.
This item exists so the dependency is visible from here.

## Summary

EPIC_002 ships the Flow UI against Cosmos with three things missing that the
user asked for on 2026-09-06: the ability to cancel a render from the tile, a
"done by" estimate, and a one-click **Extend** on a finished clip. None of
them can be built here: Flow protocol v1 has no cancel route, `Job` carries no
ETA the UI renders, and the tile has no Extend action. All three are additive
v1.x changes to the protocol plus UI work in the flow repo.

## User impact

- Today the X on a tile deletes only the browser record; the GPU keeps
  rendering for up to ~80 min. `count` is therefore locked to 1 in EPIC_002.
- Today the only ETA is a static sentence in the footer.
- Today extend is *open the picker → Videos tab → choose the clip*.

## Rough scope (flow repo)

1. **Protocol v1.1 (additive):** `DELETE /flow/jobs/{id}` → 204; optional
   `capabilities.cancel: true` so the UI shows the control only when the
   backend supports it. Optional `Job.eta_s: number|null` rendered as a
   "~N min left" line when present.
2. **UI:** X on a running tile calls DELETE before removing the record; an
   **Extend** action on a done video tile that pre-fills the composer's
   reference with that tile's `media_id`.
3. **Sidecar (this repo, after 1+2 ship):** implement the route on
   `flow/gateway.py` and bump `FLOW_VERSION`. Then re-open the `count` question.

## Dependencies / constraints from this box

- The only real cancel here is `DELETE :8002/jobs/{id}?hard=true`, which
  restarts the engine (~3.5 min) and forgets **every** queued job. A soft
  delete leaves the GPU busy (CLAUDE.md §6). The UI copy must say so.
- `eta_s` already exists on `GET :8002/jobs/{id}`; the sidecar can pass it
  through unchanged once the UI reads it.

## Open questions

- Should cancel be offered at all given it is engine-wide? Or only when the
  cancelled job is the one occupying the GPU and nothing else is queued?
- Queue-position ETA (job N of M) would need the sidecar to track submissions
  — is that worth it if `count` stays at 1?
