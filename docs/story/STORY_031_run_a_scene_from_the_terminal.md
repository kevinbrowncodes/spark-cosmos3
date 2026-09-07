# STORY_031 — Run a scene from the terminal, gated or zero-shot

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Depends on:** STORY_029, STORY_030; **BUG_006 fixed** (Ollama reachable from containers) and the memory gate passing — for the E2E
**Unblocks:** STORY_032 and flow EPIC-003 (the UI drives the same routes this CLI does)

As the operator, I want to start, review, approve and watch a scene from a
terminal on the Spark — before any UI exists — so that the agent is usable
today, and so that the first real multi-clip render on this box is driven by
a script that can be re-run rather than by hand.

## Acceptance Criteria

- [x] `scripts/flow_agent.sh` wraps the routes: `skills` (list), `plan <seed> <skill> [count]` (dry: prints the scripts, renders nothing), `run <seed> <skill> [count] [--zero-shot] [--size WxH] [--length N]`, `show <run>` (scripts, titles, summary, state, per-clip status), `edit <run> <n>` (opens `$EDITOR` on script n, PATCHes on save), `rewrite <run> <n>`, `approve <run>`, `resume <run>`, `watch <run>` (polls until a terminal state, printing the step label and clip progress on one updating line), `list`
- [x] `<seed>` may be a media id (`in:…`, `out:…`) **or a local file path**, which the script uploads first through `/flow/uploads`
- [x] `--zero-shot` sets `autostart: true` — the run goes from plan straight to `queued` with no review (EPIC_003 decision: confirm Always by default, Never on request)
- [x] The script refuses to `run`/`approve` when the memory gate would fail (`free` below `AGENT_MIN_FREE_GIB`), printing the shortfall — the executor would only pause it anyway, but a person at a terminal should be told before they walk away
- [x] `watch` exits 0 on `done`, 1 on `failed`, and prints the media ids of the finished clips
- [x] README's Flow section documents the agent: what a skill is, where they live, the four-step flow (plan → review → approve → watch), and the zero-shot switch
- [ ] **E2E on the box: a 3-clip run at 832×480 from `input_cap_guy.jpg` with `example-forecast-scene`**, watched to `done` (~72 min): three clean 10 s clips in the picker, `clips[*].media_id` resolvable, each clip's tile carrying its script and the gateway's upsampled prompt; the run JSON and `watch` transcript saved under `docs/evidence/story-031-agent-run/`
- [ ] Also on the box: `plan` with a count-locked skill returns one script; a `rewrite` of one script changes only that script
- [x] `flow/` stays ≥ 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

**Bash + curl + python3 for JSON**, like `flow_e2e_renders.sh`. No new
Python package; the script is a thin client so that the UI, when it arrives,
is exercising exactly the same surface.

**Why a gate in the script too.** The executor's gate is the safety net; the
CLI's check is the courtesy — a person about to leave the box for an hour
should know now that clip 1 will sit `paused` rather than find out later.
Same numbers (`/proc/meminfo` MemAvailable, `AGENT_MIN_FREE_GIB` default 30).

**`watch` output** is one line, rewritten in place:
`run_ab12… · Rendering clip 2 of 3 · 38 % · 00:41:12` — the run's `step`,
the current clip's `progress`, elapsed time. On a terminal state it prints
the final step and the clip media ids and exits.

**The E2E is the first real multi-clip render on this box since the July
production runs**, and the first ever through the agent. It needs three
things that are outside this repo's control: BUG_006 fixed (Gemma reachable),
≥ 30 GiB free (the executor's gate), and ~72 minutes of GPU. It is run by
this script, not by hand, so it can be repeated.

**Gemma is loaded twice per clip** during a run: once by the planner (before
review) and once by the gateway's upsampler at each submission. Both evict
immediately (`keep_alive: 0` / STORY_022). This is expected and is why the
plan step costs ~2 min of wall clock.

## Testing Plan

- **Unit**: not applicable to bash — the script's JSON handling is python3 one-liners exercised by the contract layer; no Python module changes in this story.
- **Integration**: not applicable — no new routes; STORY_030's suite already covers every route the script calls.
- **Contract** (`flow/tests/contract.sh` + a new `flow/tests/cli_contract.sh`): with the sidecar running and Ollama faked by a local `python3 -m http.server`-style stub? — **no**: the contract test runs `skills`, `list`, and `plan --help` against the real sidecar, and `run` against a count-locked skill only if Ollama is reachable, else prints SKIP. Asserts exit codes and that `plan` renders nothing (`/flow/media` unchanged).
- **E2E**: the 3-clip run above, plus the count-locked plan and the single rewrite.
- **Coverage**: unchanged — no Python changes; the gate is `--cov=flow --cov-fail-under=95` as always.

## Estimated Complexity

**Small code, long wall-clock.** ~150 lines of bash; the render is 72 minutes
when the box allows it.
