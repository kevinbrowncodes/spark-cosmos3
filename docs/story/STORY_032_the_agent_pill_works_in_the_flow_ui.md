# STORY_032 — The Agent pill works in the Flow UI

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Depends on:** STORY_029–031 (the backend, proven by the E2E run); **flow EPIC-003 STORY-601–606 released** (Agent UI + the `/flow/agent/*` protocol surface, tagged)
**Blocked until:** a flow release carrying Agent mode exists

As someone using the Flow UI, I want the Agent pill to do what the CLI does —
pick a skill and a count, read the plan, approve it, and watch the clips fill
in — so that the whole scene workflow lives in the browser.

## Acceptance Criteria

- [ ] `FLOW_VERSION` bumped to the flow release that ships Agent mode; image rebuilt; `flow-conformance` passes including its agent checks
- [x] `capabilities.agent` is declared by the sidecar with the count range, default confirm mode and the run fields, exactly as flow `PROTOCOL.md` specifies after STORY-601
- [x] The sidecar serves the protocol-shaped `/flow/agent/*` routes as a **mirror of `/agent/*`** — same handlers, no second implementation; the CLI keeps working unchanged
- [ ] In the browser: the pill fills white and the model chip hides; the instruction picker lists `data/prompts`; agent settings expose confirm Always/Never and the defaults; a run created in the UI appears as a batch of `count` tiles that fill in order, with the run's `step` shown; a run created by the CLI appears in the same place
- [ ] The review view edits and rewrites scripts and approves; a paused or failed run shows its reason and offers Resume
- [ ] Headless Chromium drives one run from the LAN address through review and approval (no render needed for the check: approve, confirm the run is `queued`, then resume/abandon) — evidence under `docs/evidence/story-032-agent-ui/`
- [x] `gateway/server.py`, `flow/runs.py` and the executor untouched — the UI is a client of what STORY_030 built
- [x] `flow/` stays ≥ 95 % line coverage

## Technical Notes

**One implementation, two prefixes.** `build_agent_router` already returns an
`APIRouter`; STORY-601 defines the `/flow/agent/*` shapes. The sidecar mounts
the same handlers under both prefixes (a prefix parameter, not a copy), and
translates only where the protocol's field names differ from ours.

**What this story must not do:** change how runs work. Anything the UI needs
that the run model lacks is a STORY_030 follow-on, decided with the flow side,
not a quiet addition here.

**Why it is last.** Everything before it is usable from a terminal today; this
is the landing of upstream work, and it is the third `FLOW_VERSION` bump — the
upgrade path (STORY_028's whole point) gets exercised again.

## Testing Plan

- **Unit**: prefix mounting — the same handler answers under both prefixes; any field translation.
- **Integration**: the STORY_030 suite re-run against the `/flow/agent/*` prefix (parametrised), plus `capabilities.agent` shape.
- **Contract**: `contract.sh` gains the `/flow/agent/*` checks; `flow-conformance` with agent declared.
- **E2E**: the headless browser run above. **No render** — the render path is STORY_031's E2E and does not change.
- **Coverage**: `--cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Small here, large upstream.** A prefix and a version bump in this repo; six
stories in the flow repo before it can start.
