# BUG_010 — After a 720p render the engine keeps ~113 GB, so the agent's memory gate can never pass

**Status:** Resolved 2026-09-07 (mitigation documented; durable fix is BACKLOG_005)
**Found:** 2026-09-07, STORY_032 E2E: the UI-driven 720x1280 clip finished and the resumed 3-clip run
(`run_e3bd921556a7`, 832x480) immediately paused with `8 GiB available, need 22`
**Affects:** `flow` executor gate (STORY_030, `AGENT_MIN_FREE_GIB`), `scripts/flow_agent.sh` and
`scripts/flow_e2e_renders.sh` (their advisory checks), and anyone queueing a render after a 720p one

## Summary

The gate assumes the box returns to its idle baseline between clips. It does not.
`free -g` on this box, engine idle, nothing in `ollama ps`:

| moment                                      | used   | available |
|---------------------------------------------|--------|-----------|
| after three 832x480 clips (before 16:50)    | 99 GB  | 22.5 GiB  |
| ten minutes after one 720x1280 clip (17:30) | 113 GB | 8.3 GiB   |

The vLLM-omni engine's allocator keeps the 720p peak resident for as long as the
container lives (`cosmos3-api` had been up two weeks; it grows to the largest
render it has served). With 8 GiB free the gate at 22 pauses every run, and
lowering the gate would not be safe: the gateway loads Gemma (~17 GB) for the
upsample right before each clip, and an OOM kills the largest process — the
engine (exit 137, CLAUDE.md §7).

## Steps to reproduce

```bash
awk '/MemAvailable/ {print $2/1048576 " GiB"}' /proc/meminfo     # ≥ 22 after 480p work
# render one 720x1280 clip through the gateway, wait for it to finish
awk '/MemAvailable/ {print $2/1048576 " GiB"}' /proc/meminfo     # ~8 GiB, and it stays there
scripts/flow_agent.sh resume run_e3bd921556a7 && scripts/flow_agent.sh show run_e3bd921556a7
# paused   Paused: 8 GiB available, need 22
```

## Expected vs actual

- **Expected:** a queued clip renders once the previous one is done; the gate only trips when something *else* is holding memory.
- **Actual:** the gate trips on the engine's own retained cache and the run stays paused until someone restarts the engine by hand.

## Root cause

Two halves: the engine never returns its peak allocation (upstream behaviour; the
deployment does not pass `--enable-sleep-mode`, see CLAUDE.md §7), and the gate is
an absolute `MemAvailable` threshold that cannot tell "the engine is big" from
"another model is loaded".

## Mitigation now

Restart the idle engine (`docker compose restart cosmos3`, ~3.5 min to healthy;
confirm no job is in flight first via `GET :8002/jobs/{id}` on the last job) and
resume the run. This is a manual, human decision — the engine restart wipes
queued job records.

## Acceptance criteria

- [x] The measurements above and the restart recipe are recorded in `docs/spark-notes.md`
- [x] A backlog item proposes the durable fix (executor asks the sidecar to restart an idle engine when the gate trips with no job running, or the engine runs with sleep mode) — no code from this ticket
- [x] `run_e3bd921556a7` resumed to `done` after the restart

## Resolution

Documented in `docs/spark-notes.md` (rule 4 + the restart row) and CLAUDE.md §7.
The restart recovered the box on 2026-09-07: 8.3 → 38.5 GiB available, and
`run_e3bd921556a7` resumed and reached `done`.

**Caveat found while doing it:** resuming ~12 s after issuing the restart made the
executor submit into an engine that was still loading, and the run failed with
`cosmos3 gateway: Internal Server Error` (the gateway's `httpx.ConnectError`).
A second resume after `:8000/health` returned 200 rendered clip 3 normally. So the
recipe is *restart, wait for health 200, then resume* — the executor has no
engine-readiness check of its own, which is part of what BACKLOG_005 should fix.
