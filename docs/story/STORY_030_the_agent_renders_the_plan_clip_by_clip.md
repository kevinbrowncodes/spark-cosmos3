# STORY_030 — The agent renders the plan clip by clip

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Depends on:** STORY_029 (the planner), STORY_026 (Extend + prefix trim), BUG_006 (Ollama reachable from containers — for the E2E only)
**Unblocks:** STORY_031 (CLI + confirm setting), flow EPIC-003 STORY-601 (the protocol mirror)

As someone who has approved a plan, I want the box to render clip 1 from the
seed and then extend it clip by clip until every script is done — while I am
away, surviving a sidecar restart, never submitting into a saturated box — so
that a six-clip scene is one decision, not an afternoon of babysitting.

## Acceptance Criteria

### Runs are records

- [ ] `POST /agent/runs` `{reference_id, instruction, count, values?, project_id?, autostart?}` creates a run and returns it immediately in state `planning`; planning happens in the background and the run moves to **`review`** (or straight to **`queued`** when `autostart` is true)
- [ ] A run is one JSON file under `FLOW_MEDIA_DIR/flow-runs/<id>.json`, written atomically on every transition; `GET /agent/runs` (newest first, optional `?project_id=`) and `GET /agent/runs/{id}` read it back
- [ ] The run carries: `id, project_id, title, state, step, clip_index, clip_count, instruction, count, values, reference_id, scripts[], titles[], summary, clips[{n, script, job_id, media_id, status, progress, error}], autostart, error, attempts, created_at, updated_at`
- [ ] `title` is the first line of `titles` (or `"Untitled run"`); `values` are validated and defaulted through the gateway's own capabilities — unknown keys **422** — with agent defaults **`832x480`, Length `10`**, steps 35, sound on, upsample on, `count` forced to 1 per clip
- [ ] A seed may be an image **or a video**: an image seed makes clip 1 an I2V generate; a video seed makes clip 1 an Extend of that clip (the planner sees its poster frame)

### Review

- [ ] `PATCH /agent/runs/{id}/scripts/{n}` `{text}` replaces script *n* (non-empty) while the run is in `review`; any other state → **409**
- [ ] `POST /agent/runs/{id}/scripts/{n}/rewrite` asks Gemma for a fresh script *n* only — the skill, the seed, the position "clip n of N" and the other scripts are in the prompt; exactly one `<<<SCRIPT n>>>` block is accepted; retries and failures as STORY_029
- [ ] `POST /agent/runs/{id}/approve` moves `review → queued`; **409** from any other state

### The chain

- [ ] A single executor in the sidecar renders **one run at a time**, oldest `queued` first; clip *n* is submitted only after clip *n−1* is `done` and cached
- [ ] Clip 1 uses the seed; clip *n ≥ 2* uses `out:<previous job>.mp4` as a **video** reference — the trimmed clip STORY_026 cached — so every clip is Length seconds of new footage and the chain concatenates clean
- [ ] Every submission goes through the sidecar's own `Cosmos3Gateway.generate` (the same path a UI click takes): `upsample=true`, the script as the prompt, `condition_seconds=3.0` on extends. **`gateway/server.py` is not touched**
- [ ] Before **each** submission the executor checks the memory gate: `MemAvailable ≥ AGENT_MIN_FREE_GIB` (default **30**). Below it the run becomes **`paused`** with `error` = `"22 GiB available, need 30"` and is retried on later ticks without losing its place
- [ ] Progress: `step` is a short present-tense label — `Writing 6 scripts…`, `Waiting for review`, `Queued`, `Rendering clip 2 of 6`, `Caching clip 2`, `Paused: …`, `Done`, `Failed at clip 3: …`; the current clip's `progress` mirrors the gateway's percentage
- [ ] A clip whose job the gateway reports `failed`, or no longer knows (**404** — the engine restarted), fails the run at that clip with the reason; **`POST /agent/runs/{id}/resume`** puts a `failed`/`paused` run back to `queued` **at the same clip**
- [ ] After a sidecar restart the executor reloads every run: a `rendering` run keeps polling its current job; a `planning` run is planned again; `review`/`queued`/`done` are untouched
- [ ] Finished clips are ordinary media: they appear in `/flow/media` and the picker, each with a poster, and `clips[n].media_id` names them

### Plumbing

- [ ] `AGENT_MIN_FREE_GIB` and `AGENT_TICK_S` (default 5) are environment settings; documented in `.env.example`
- [ ] `flow/tests/contract.sh` checks `GET /agent/runs` → 200 array
- [ ] `flow/` stays ≥ 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

**The executor is a tick, not a thread.** `Executor.tick()` does exactly one
unit of work — plan a `planning` run, submit the next clip of the active run,
or poll it — and returns. A background `asyncio` task in the app's lifespan
calls it every `AGENT_TICK_S`; the tests call it directly and walk a run to
`done` with the gateway faked. No sleeps in tests, no races.

**The gateway object is the client.** `Cosmos3Gateway.generate()` and `.job()`
already do everything a clip needs — reference-kind dispatch, frame maths,
caching on `done`, prefix trimming — and they are what the UI's own clicks go
through. Calling them in-process (via `asyncio.to_thread`, they are sync)
means the agent can never diverge from a manual generate. The run's
`values` go through `flow_protocol.normalise_request` against the live
capabilities, so a bad size or length is a 422 at run creation, not a failed
clip an hour later.

**Why 480p by default.** EPIC_003's table: a 6-clip scene is ~2.5 h at 832×480
and ~7.6 h at 704×1280. The pipeline renders 480p and upscales for the same
reason. A run can ask for 720p in `values`; the default protects the box.

**The memory gate inside a container.** `/proc/meminfo` is not namespaced, so
`MemAvailable` read from inside `flow` is the host's number — the same one
`scripts/flow_e2e_renders.sh` gates on. The kernel-log NVRM check is not
reachable from a container and is not replicated; the gate is memory only.

**Video seeds.** The planner (STORY_029) needs an image. For a video seed the
executor hands it the clip's poster frame — `gateway.thumbnail_path()` already
makes one with ffmpeg — and clip 1 becomes an Extend of that clip. This is what
lets a run continue a scene from a clip a previous run produced.

**Rewrite prompt.** Same skill as system prompt (count substituted with the
run's count), then a user turn: the seed image, *"Rewrite ONLY script n of N.
Keep every other script as written. Current scripts: …"*, and the instruction
to emit exactly one `<<<SCRIPT n>>>` block. `parse_single(text, n)` accepts one
block numbered *n* (or a marker-less reply). Titles and summary are **not**
regenerated — EPIC_003 known limitation 4.

**Run ids** are `run_<12 hex>`; **titles** come from the plan's first title
line, emoji and all, matching how the skills already name things.

**What is deliberately not here:** cancel (the gateway cannot stop GPU work —
CLAUDE.md §6), concatenation, more than one run rendering at once.

## Testing Plan

- **Unit** (`test_agent_runs_unit.py`): `RunStore` save/load/list ordering, atomic write (a `.tmp` never left behind), `Run` transitions and `step` labels for every state, `mem_available_gib()` parsing a fixture `/proc/meminfo`, `parse_single` (one block numbered n; wrong number; marker-less), title derivation.
- **Integration** (`test_agent_runs_routes.py`, `respx` on both the gateway and Ollama): create → `planning`; one `tick()` → `review` with 3 scripts; PATCH script 2; rewrite script 3 (payload asserts "ONLY script 3 of 3"); approve → `queued`; ticks: gate passes → clip 1 submitted with `name="image"` → poll running (progress mirrored) → done → clip 2 submitted with `name="video"` + `condition_seconds=3.0` and `reference_id == out:<job1>.mp4` → … → `done` with three `media_id`s; `autostart: true` skips review; 409s for PATCH/approve in the wrong state; gate below threshold → `paused` with the exact message, then passes on a later tick; gateway `failed` → run `failed` at that clip, `resume` → `queued` at the same clip; gateway 404 on the job → same; restart: a new `Executor` over the same dir resumes a `rendering` run and re-plans a `planning` one; values 422 for a bad size; video seed → clip 1 posts `name="video"`.
- **Contract**: `contract.sh` — `GET /agent/runs` → 200 array.
- **E2E**: a **3-clip run at 832×480** on the box (~72 min): three clean 10 s clips in the picker, `clips[*].media_id` resolvable, run `done`. Held until BUG_006 is fixed and the memory gate passes; the executor's own gate is exercised in the process.
- **Coverage**: `--cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Large.** The run store, the state machine, the executor and its restart
behaviour are the heart of the epic; the tests are the bulk of the work.
