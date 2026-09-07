# BACKLOG_003 — Promote the reusable parts of our Flow sidecar into the flow library

**Status:** Open
**Priority:** Medium — do it before the second repo adopts Flow, not after
**Raised:** 2026-09-07 by Kevin: *"in the future I want to take all the changes we did here so I can use the library with other models in other repos I created dedicated for them."*
**Where the work lands:** `kevinbrowncodes/flow` (cloned at `~/Documents/GitHub/kevinbrowncodes/flow`), then a `FLOW_VERSION` bump here.
**Related:** EPIC_002, STORY_023–027, BUG_005, BACKLOG_002

## Summary

EPIC_002 built a lot inside `flow/gateway.py` and `flow/app.py` that has
nothing to do with Cosmos. Today those live in this repo as a fork of
upstream's `examples/cosmos3.py` (202 diff lines against the pinned
`ea380b93…` copy). The next model repo — `spark-ltx2` already has an upstream
example — would have to copy-paste them. They should move into the library so
each backend implements only what is genuinely its own.

## What is generic (belongs in the library)

| Ours today | Belongs as | Why it is not Cosmos-specific |
|---|---|---|
| `trim_prefix`, `has_audio` (STORY_026) | `flow_protocol.video` | Any V2V backend returns a recycled conditioning prefix; a frame-accurate cut is the same ffmpeg recipe everywhere |
| `_cache_output` / `_finalise_output` on `done` (STORY_025) | base `FlowGateway`, with a `finalise()` hook | Any backend whose upstream forgets jobs on restart loses unviewed clips |
| Serving the UI at `/flow/` + `/` redirect (STORY_027) | `router.mount_ui` / `create_app` | Nothing to do with the model |
| `crypto.randomUUID` shim (BUG_005) | `src/adapter/contract.js` — a real fix, not a shim | Every LAN-hosted backend hits it; our injection then becomes a no-op |
| "Remember the request, do not trust the payload" for `duration_s` | documented pattern, maybe a small `JobMemo` helper | LTX's payload fields differ but the trap is identical |
| Reference-kind dispatch (image → one field, video → another) | a documented pattern + helper | Any backend offering both I2V and V2V |
| `respx`-faked route suite, in-process `run_checks`, `contract.sh`, `e2e_ui_generate.py` | `flow_protocol.testing` + a `flow-e2e` console script | The Playwright driver only touches the shipped UI's aria-labels — it is already model-agnostic |
| Dockerfile shape: one `FLOW_VERSION` for both artefacts, tests in a build stage | a documented template in `protocol/python/README.md` | Every sidecar wants this |

## What stays here (genuinely Cosmos)

- `snap4k1` / `frames_for` **values** — 4k+1 is Cosmos's VAE, 73 frames is our
  3 s conditioning decision (EPIC_001). The *shape* (a Length control in
  seconds of new video → backend frames) is generic and should become a
  library helper that each backend fills in.
- `LENGTHS = [5, 8, 10]`, the size list from `resolution_ratio_dict.json`,
  steps `[35, 50]`, the `reasoner` field, `count` locked to 1, the footer text.
- Everything about `condition_seconds` and the gateway's 2 s–10 s duration schema.

## Open questions

- Does the generic half go into `flow_protocol` proper, or a
  `flow_protocol.contrib` so the core stays small?
- Do we keep `examples/cosmos3.py` upstream in sync with our fork, or delete it
  upstream once this repo owns the real one? (Today it is a stale copy of what
  we started from.)
- `flow_protocol.testing` would pull `respx`/`playwright` — an extra
  (`flow-protocol[testing]`), not a core dependency.

## Definition of ready (before this becomes stories)

- The generic list above is confirmed against a *second* real backend
  (`spark-ltx2`), not just Cosmos — that is what proves a thing is reusable
- A protocol version decision: all of this is additive, so it should be v1.x
