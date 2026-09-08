# BUG_013 — Redeploying the flow sidecar kills any run or check that is polling it

**Status:** Open
**Found:** 2026-09-07, deploying the STORY_033 fix while STORY_025's conformance render was polling
**Affects:** `scripts/deploy.sh`, and any `docker compose up -d … flow` done by hand

## Summary

`docker compose up -d --build flow` recreates `cosmos3-flow`. Anything holding an HTTP
connection to it dies mid-request: the STORY_025 conformance run had been polling
`GET /flow/jobs/{id}` for 17 minutes and fell over with

```
httpx.ReadError: [Errno 104] Connection reset by peer
```

The render it had started kept going on the engine — engine aborts are bookkeeping only —
so the GPU stayed busy for a job whose watcher was gone, and the check had to start again
from zero. The deploy itself succeeded and looked clean; nothing warned that a check was in
flight.

The same applies to an agent run: the executor lives inside the sidecar, so recreating it
mid-render orphans the engine job. The run record survives (it is on disk) and the executor
re-reads it, so an agent run recovers — but a conformance or E2E client does not.

## Steps to reproduce

```bash
./scripts/flow_e2e_renders.sh conformance &   # starts a render, polls /flow/jobs/{id}
GIT_SHA=$(git rev-parse --short HEAD) docker compose up -d --build --no-deps flow
# the background check dies with ECONNRESET; the engine keeps rendering
```

## Expected vs actual

- **Expected:** deploying refuses, or at least warns loudly, while something is mid-render
  through the sidecar — the same courtesy `flow_e2e_renders.sh` already extends to the engine
  before it submits.
- **Actual:** it recreates the container silently and the check dies.

## Fix

`scripts/deploy.sh` gains the same activity check the render script uses before it submits:
an agent run in `rendering`, or a gateway job that is `queued`/`in_progress`, means abort with
an explanation. `--force` overrides for the case where the sidecar is what is broken.

## Acceptance criteria

- [ ] `./scripts/deploy.sh` aborts with a clear message when an agent run is rendering or the newest gateway job is still running
- [ ] `--force` proceeds anyway and says what it is overriding
- [ ] Deploying with the box idle is unchanged
