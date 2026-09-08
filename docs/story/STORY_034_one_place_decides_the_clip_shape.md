# STORY_034 — One place decides the clip shape

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Depends on:** flow STORY-608 (the rule moves into `flow_protocol`, released)
**Follows:** STORY_033, which put the rule here first

As the person maintaining this box, I want the size-from-seed rule to live in the flow
protocol rather than in this repo, so that the Flow UI can show me the shape I am about to get
without a second copy of the rule quietly disagreeing with the first.

## Acceptance Criteria

- [x] `flow/runs.py` imports `size_for_seed` from `flow_protocol` and no longer defines its own
- [x] Behaviour is unchanged: the STORY_033 cases still hold, checked against the same shared
      vectors the upstream suite uses
- [ ] `FLOW_VERSION` is the release that carries the rule and the composer display
- [ ] The Flow UI on this box shows the corrected size **before** Generate is pressed, for both
      an uploaded photo and a clip picked for an Extend
- [x] `probe_dimensions` stays here — measuring a local file is this sidecar's job, not the
      protocol's
- [x] `flow/` stays at or above 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

STORY_033 deliberately put the rule in `flow/runs.py` to fix a live problem the same day. It is
generic — any gateway that conditions on a first frame needs it — so it belongs upstream, which
is also the only way the browser can apply it without a second implementation drifting from
this one (flow STORY-608 covers that half).

The import swap is small. The care is in the vectors: the upstream file must contain the cases
this repo relies on, including the two that came from real incidents — a 1376x768 photo asked
for at `720x1280` yielding `1280x720`, and a 768x1376 photo asked for at `832x480` yielding
`480x832`.

`DEFAULT_TIER` stays here: what the agent is willing to spend is this deployment's policy, not
the protocol's.

## Testing Plan

- **Unit** — required. The existing `test_agent_size_unit.py` cases run unchanged against the
  imported function, proving the swap is behaviour-preserving; the local `size_for_seed` tests
  are deleted along with the local implementation, and the shared vectors are asserted.
- **Integration** — required. `POST /agent/runs` cases from STORY_033 stay green.
- **Contract** — required. The opt-in `CONTRACT_AGENT_SIZE=1` check still passes.
- **E2E** — required, no render: on the box, attach a landscape photo in the browser and read
  the size shown in the composer before pressing Generate, then create the run and confirm the
  record agrees. That is the whole point of the story and cannot be checked any other way.
- **Coverage** — `pytest --cov=flow --cov-fail-under=95`.

## Estimated Complexity

Small here, once the upstream release exists. Blocked on flow STORY-608.
