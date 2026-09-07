# STORY_029 — The agent writes the scripts

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Depends on:** STORY_022 (Gemma via Ollama is the box's reasoner), STORY_023–026 (the `flow` sidecar and its media store)
**Unblocks:** STORY_030 (runs and the render chain)

As someone planning a scene, I want to attach a seed image, pick one of my
skills and a clip count, and get back every script — plus the titles and the
arc summary my skills already produce — in one call, so that I can read the
whole plan before a single GPU-minute is spent.

## Acceptance Criteria

### The library

- [x] `GET /agent/instructions` lists every `data/prompts/*.md` as `{id, name, description, count_locked}` — `id`/`name` from frontmatter `name` (filename stem if absent), `description` from frontmatter (first sentence), `count_locked: true` when the body has no `{{COUNT}}`
- [x] The list reflects the directory on every call — dropping a file in takes effect on the next request, no restart
- [x] A file with no frontmatter still lists (stem as name, empty description); a non-`.md` file is ignored

### The plan

- [x] `POST /agent/plan` with `{reference_id, instruction, count}` returns `{instruction, count, scripts[], titles[], summary, attempts, model}`; `scripts` has **exactly `count`** entries
- [x] `count` defaults to 1, must be ≥ 1, and is **422** when > 1 for a count-locked skill; unknown `instruction` → **404**; unknown or non-image `reference_id` → **404 / 422** (a video seed arrives in STORY_030)
- [x] The skill body is sent as the **system** message with every `{{COUNT}}` replaced by the number; the seed image goes as a base64 `images` entry on the user turn; the request pins `options.num_ctx = 32768` and `keep_alive = 0` so Gemma is evicted after the reply (STORY_022's rule — it must not sit resident)
- [x] The reply is parsed by the epic's contract: `<<<SCRIPT n>>>…<<<END SCRIPT>>>` blocks in order, optional `<<<TITLES>>>` (one per line) and `<<<SUMMARY>>>`; a marker-less reply with `count = 1` is accepted as the single script
- [x] A wrong script count, an unparsable reply, or empty content is a **content failure**: retried immediately, up to **5 attempts**; transport failures (Ollama down, 5xx, timeout) retry the same way; after the last attempt → **502** whose `detail` names the reason (`"expected 6 scripts, got 1"`, `"ollama unreachable: …"`)
- [x] `attempts` in the response is the number of Gemma calls made; `model` is the model name used
- [x] Nothing is rendered, cached, or written to disk by this story — a plan is a pure response

### Plumbing

- [x] The `flow` service gets `extra_hosts: host.docker.internal:host-gateway`, `GEMMA_URL` (default `http://host.docker.internal:11434`), `GEMMA_MODEL` (default `gemma4:26b`) and `PROMPTS_DIR` (default `/data/prompts`); `.env.example` documents the first two beside the gateway's identical ones
- [x] `flow/tests/contract.sh` checks `GET /agent/instructions` → 200 with a valid array (empty allowed on a fresh box)
- [x] `gateway/server.py` untouched; `flow/` stays ≥ 95 % line coverage

## Technical Notes

**Routes live outside `/flow`.** `/agent/*` is this backend's own surface, not
the Flow protocol. When the Agent UI lands upstream it will call the additive
`/flow/agent/*` mirror of these routes; until then the CLI (STORY_031) and
curl are the clients. Keeping them apart means a `FLOW_VERSION` bump can never
collide with them.

**Module layout.** `flow/agent.py` — pure library: `load_instructions(dir)`,
`render_prompt(skill, count)`, `parse_plan(text, count)`, `class Planner`
(async, `httpx`, holds `GEMMA_URL`/`GEMMA_MODEL`). `flow/app.py` mounts
`build_agent_router(gateway, planner)`; the gateway is only used to resolve
`reference_id` → path through the existing media store, so the seed can be an
`in:` upload or an `out:` clip's poster later.

**Why the native `/api/chat`, not the OpenAI shim.** `options.num_ctx` and
`keep_alive` are only honoured on Ollama's native API. Measured 2026-09-07 on
this box: the same 10k-token prompt took 219 s at the default 262k context and
102 s at 32k — the KV cache for 262k is both slow and large, and the box has
24 GiB to spare beside the engine. `keep_alive: 0` mirrors STORY_022's eviction,
which exists because a resident Gemma once pushed a production render into
swap.

**System vs user.** The whole skill goes in the `system` role with `{{COUNT}}`
substituted; the user turn is the image plus one line — `"The seed image is
attached. COUNT = 3."` — so the count appears in both places the skills expect
it (their banner and their Output section) and once more where the model
looks last.

**The parser is strict on purpose.** "Sometimes only one script" is by design
for single-clip skills (Kevin, 2026-09-07), so `count_locked` handles those.
For a `{{COUNT}}` skill, fewer or more blocks than asked is a failure the
render chain must never see: rendering one clip when six were planned costs an
hour and produces nothing usable. Retries are immediate (a local model has no
rate limit) and the failure is loud.

**Temperature is the model's own** (the Modelfile sets 1.0). The skills rely
on creative variation; the count banner, not sampling, is what enforces the
count. If retries turn out to be frequent on a specific skill, that is a skill
problem to fix in `data/prompts/`, not a reason to lower temperature here.

**Timeouts.** Gemma at 32k context on this box: ~100 s for a 10k-token prompt
plus image plus a 2–3k-token reply. The planner's per-attempt timeout is
**600 s**; five attempts could take most of an hour in the worst case, which
is acceptable for a call that gates hours of rendering.

## Testing Plan

- **Unit** (`flow/tests/test_agent_unit.py`): frontmatter parsing (name, description first sentence, missing frontmatter, count_locked detection); `render_prompt` replaces every `{{COUNT}}` and leaves a locked skill untouched; `parse_plan` — exact count, fewer, more, out-of-order numbering, missing `<<<END SCRIPT>>>`, marker-less + count 1, marker-less + count 3 (fail), titles and summary present/absent, surrounding chatter ignored, whitespace trimmed.
- **Integration** (`flow/tests/test_agent_routes.py`, `respx` on `GEMMA_URL`): instructions list from a tmp dir (with a fixture skill copied in; hot reload by adding a file between calls); plan happy path asserting the outgoing payload (system text contains "exactly 3", `images[0]` is the seed's base64, `num_ctx` 32768, `keep_alive` 0, model name); wrong-count twice then right → `attempts = 3`; five wrong → 502 with `"expected 3 scripts, got 1"`; Ollama unreachable → 502; unknown instruction → 404; count 2 on a locked skill → 422; missing reference → 404; video reference → 422.
- **Contract**: `contract.sh` — `GET /agent/instructions` → 200, JSON array, every entry has the four keys.
- **E2E**: on the box, with Kevin's skills in `data/prompts/`: `POST /agent/plan` with `input_cap_guy.jpg`, a scene skill, `count = 3` → three scripts, titles, summary; and a single-clip skill with `count = 1`. Gemma loads (~18 GiB) and is evicted after — verified by `ollama ps` showing nothing resident. **No render.**
- **Coverage**: `python3 -m pytest --cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Medium.** ~200 lines of library code and one router; the parser and the
retry loop are where the tests concentrate. The E2E needs the skill files
Kevin is copying in.
