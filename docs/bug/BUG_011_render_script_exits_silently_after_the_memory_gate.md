# BUG_011 — The E2E render script exits silently after the memory gate

**Status:** Resolved 2026-09-07
**Found:** 2026-09-07, running `./scripts/flow_e2e_renders.sh ui` for STORY_025
**Affects:** `scripts/flow_e2e_renders.sh` — every phase, whenever `data/logs/jobs/` is large

## Summary

`scripts/flow_e2e_renders.sh ui` printed its two memory-gate lines, exited **0**, and did
nothing: no browser, no job, no evidence directory. It looked exactly like a successful
no-op, which is the dangerous part — a scheduled run would report success having rendered
nothing. The same applied to `conformance`, `extend` and `all`.

## Steps to reproduce

```bash
ls data/logs/jobs | wc -l        # ~700 files on this box
./scripts/flow_e2e_renders.sh ui
# memory gate: 30 GiB available, 0 NVRM/OOM line(s)
# $? = 0, and nothing else happens
bash -x ./scripts/flow_e2e_renders.sh ui | tail -3   # trace stops mid-gate
```

## Expected vs actual

- **Expected:** the gate passes, then the phase runs (or the script aborts loudly).
- **Actual:** the script exits between the gate's checks, silently, with status 0.

## Root cause

Inside `gate()`:

```bash
last=$(ls -t data/logs/jobs | head -1)
```

`head -1` exits as soon as it has its line; `ls` then writes into a closed pipe, takes
SIGPIPE and exits **141**. The script runs under `set -euo pipefail`, so `pipefail` makes
the command substitution inherit 141 and `set -e` terminates the script. It only shows up
once the directory is big enough that `ls` is still writing when `head` leaves — which is
why the script worked for months and then stopped. The identical expression inside
`if [ -n "$(…)" ]` is harmless, because there the `[` builtin's status is what `set -e`
sees; the bare assignment is what kills it.

## Resolution

Read the newest entry once, with `pipefail` disabled for that substitution only:

```bash
last=$(set +o pipefail; ls -t data/logs/jobs 2>/dev/null | head -1)
```

Each phase also now creates the evidence directory it `tee`s into, so running a single
phase works (only `phase_conformance` used to create `docs/evidence/STORY_025`, and `tee`
cannot create a directory — a second silent-exit path).

## Acceptance criteria

- [x] `./scripts/flow_e2e_renders.sh ui` reaches the browser: the trace shows the gate finishing, `last gateway job …` printed, then the driver's `secure context:` line
- [x] Each phase creates its own evidence directory
