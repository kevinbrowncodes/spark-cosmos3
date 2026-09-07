# BACKLOG_005 — Recover the engine when the memory gate trips on an idle box

**Priority:** High — every agent run that follows a 720p clip pauses (BUG_010)
**Source:** BUG_010, 2026-09-07

## Summary

The agent's executor pauses a run when `MemAvailable` is below `AGENT_MIN_FREE_GIB`.
After a 720x1280 render the engine keeps ~113 GB resident for the life of its
container, so the gate trips with nothing else running and the run waits for a
human to restart the engine. The sidecar already knows how to restart the engine
(the gateway's hard-cancel path does it through the progress sidecar, ~3.5 min).

## User impact

A queued multi-clip run silently stops after the first 720p clip; Kevin finds it
`Paused: 8 GiB available, need 22` in the morning.

## Rough scope

Pick one:

1. **Executor asks for an engine restart.** When the gate trips *and* the gateway
   reports no job in flight, the executor requests the sidecar's engine restart,
   waits for `:8000/health`, re-checks memory, and submits. Needs a "restart in
   progress" state so the UI shows what is happening, and a cap so a box that is
   genuinely full (another model loaded) does not restart the engine in a loop.
2. **Sleep mode.** Start the engine with `--enable-sleep-mode` and have the
   gateway call `/v1/omni/sleep` between jobs and `/v1/omni/wakeup` before one.
   Cheaper per cycle than a restart, but changes the engine command line
   (`docs/container.md`) and the wakeup latency is unmeasured on GB10.
3. **Smarter gate.** Gate on "memory not attributable to the engine" rather than
   an absolute number — hard on unified memory where `docker stats` lies
   (CLAUDE.md §7); probably not enough on its own.

## Dependencies

- BUG_010 measurements; BUG_004 (the engine emits no logs, so "idle" must come from the gateway's job records, not `docker logs`)
- Option 2 depends on a container.md update and a sleep/wakeup timing test

## Also in scope: engine readiness

Resuming a run while the engine is still loading fails it outright
(`cosmos3 gateway: Internal Server Error` — the gateway cannot connect, BUG_010's
resolution note). Whatever restarts the engine must also wait for `:8000/health`
before submitting, and a submit that fails with a connection error should pause
the run rather than fail it.

## Open questions

- Does the engine's resident set also grow after long 480p V2V chains, or only after larger frames?
- Should the restart be automatic, or should the UI show a "Restart engine and resume" button (a human decision, as today, but one click)?
