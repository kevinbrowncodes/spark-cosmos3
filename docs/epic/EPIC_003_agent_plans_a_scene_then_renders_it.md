# EPIC_003 — The agent plans a scene, then renders it

**Status:** Done 2026-09-08 — STORY_029 through STORY_034 closed. The agent plans from Kevin's own skills, renders chains three clips deep with exact 24 fps Extends (BUG_007), takes the clip's shape from the seed (STORY_033) with the rule living upstream so the Flow UI previews it before a render (STORY_034 / flow STORY-608, `v0.2.1`), and ran two unattended 30-second scenes overnight (`docs/evidence/overnight-2026-09-07/`). Open, upstream: flow BUG-003 (a waiting run cannot be acted on from the grid), BUG-004 (batch metadata goes stale), STORY-607 (seed as poster). Open here: BUG_014 (720p Extend clamp), BACKLOG_005 (engine recovery in the executor), BACKLOG_008 (join the scene automatically).
**Stories:** STORY_029 → STORY_032 (this repo) · Agent UI in `kevinbrowncodes/flow` (its own epic, referenced below)
**Related:** EPIC_001 (Extend), EPIC_002 (Flow UI), BACKLOG_003 (library promotion), BACKLOG_004 (project storage), flow `RECON-10-agent-mode.md`
**Decided:** 2026-09-07 with Kevin — see *Decisions*

---

## Goal

Today a multi-clip scene is made by hand: run one of Kevin's skill prompts through
Gemma with `{{COUNT}}` set, wait for a clip, click Extend, paste the next script,
wait, repeat — for up to six clips and several hours. The pipeline in
`ogtv-studios` automates the same loop from the command line.

This epic puts that loop behind one button in the Flow UI, with the one thing
the manual loop never had: **a review of the plan before the GPU-hours are
spent.**

> Attach a seed, pick a skill, choose how many clips. The agent writes every
> script, shows them to you with the arc summary, and — once you say so —
> renders clip 1 from the seed and extends it clip by clip until the scene is
> done, with the clips landing in the project like any other tiles.

### What Google's agent is, and what ours is

RECON-10 shows Google's Agent mode as a **conversational creative director**:
plan → confirm → generate, a reusable instruction library, a settings panel,
server-side sessions, reasoning-step labels. The conversation sits *on top* of
that shape.

Ours keeps the shape and drops the conversation. The language step is
**one shot** — a single Gemma call writes all N scripts, titles, and the
summary. The workflow is **two steps with a gate** — plan, review, approve,
render. The reason is arithmetic, not taste: Google's confirm protects ~15
credits and their clips take a minute; ours protects **2.5–7.6 GPU-hours**
and the plan step costs two minutes.

| Google (RECON-10) | Here |
|---|---|
| "Agent instructions" — titled, toggleable guidelines | Kevin's skill files in `data/prompts/`, picked per run |
| "Agent settings" — confirm Always/Never, per-mode defaults | Confirm-before-render (Always default), default size, default count |
| Storyboard → "Does this look good?" | Scripts + the `<<<SUMMARY>>>` arc table → Approve |
| "make shot 2 slower" revises in place | Edit script text, or **Rewrite** one script (fresh Gemma call, others held) |
| Sessions: server-side, per-project, auto-named | Runs: server-side, per-project, auto-named from `<<<TITLES>>>` |
| Reasoning-step labels, no token streaming | "Writing 6 scripts…" → "Rendering clip 2 of 6 · 38%" → "Trimming…" |
| "Show thinking" | The arc summary and, per clip, the upsampled prompt the gateway already returns |
| Chat transcript, suggestion chips, thumbs/flag, credits | **Not built** — no value for a deterministic pipeline |

## Scope

**In scope**

- A **prompt library** at `data/prompts/*.md` (Kevin's skills, frontmatter-named), served to the UI as the instruction list.
- A **planner**: seed image + skill + count → N scripts, titles, summary. Gemma via Ollama, the same model the gateway upsamples with. Count validated; retried on content failures the way STORY_022 retries the upsampler.
- **Runs**: server-side, durable, resumable records that carry the plan through review and drive the render chain — clip 1 I2V from the seed, clips 2..N via Extend (last 3 s), each clip trimmed and cached exactly as STORY_026 does today.
- **Review**: edit any script's text, rewrite any one script, approve. A setting flips the gate off for zero-shot runs.
- A **CLI** so the whole thing is usable from a terminal before any UI exists.
- The **Agent UI** in the flow repo, behind an additive protocol surface — scoped and tracked there, landed here by a `FLOW_VERSION` bump.

**Out of scope**

- Conversation. No transcript, no clarifying questions, no LLM-chosen tools.
- Changing how a single clip is rendered — every clip is a normal `/generate` call through the existing gateway contract. `gateway/server.py` is not edited by this epic.
- Concatenating the finished clips into one file (a natural follow-on; today the pipeline and Topaz do it).
- More than one run rendering at a time. The engine serialises jobs; runs queue.

---

## Decisions (2026-09-07)

| Question | Decision | Why |
|---|---|---|
| Confirm gate | **Always by default; a setting turns it off** for zero-shot runs | The plan costs two minutes, the render costs hours. Kevin wants the option to queue a trusted run without looking |
| Revising a script | **Edit text in place + a Rewrite button** per script | Precise, and needs no chat surface. Rewrite is one Gemma call with the other scripts held fixed |
| Where the skills live | **`data/prompts/`** in this repo | Versioned with the code that reads them, synced like the rest of `data/`, mounted read-only. Frontmatter `name`/`description` drives the picker |
| Chain mode for clips 2..N | **Extend, last 3 s** (`condition_seconds=3.0`) | What EPIC_001 built and its blind A/B favoured. The skills' forward-facing ending is the last thing inside the 3 s window, so their anti-drift rule still applies |
| Single-script skills | `count` is a first-class input from **1** upward; a skill without `{{COUNT}}` is count-locked to 1 | "Sometimes only one script" is by design — some skills are single-clip on purpose |
| Where the agent runs | **In the `flow` sidecar**, server-side | A 2.5-hour chain outlives a browser tab; client-side orchestration would drop clips 4–6 the moment the laptop sleeps |

---

## Shared technical constraints

### The skill output contract (already true of every scene skill)

```
<<<SCRIPT 1>>> … <<<END SCRIPT>>>   × count
<<<TITLES>>>   one title per line, strongest first, emoji-led   <<<END TITLES>>>
<<<SUMMARY>>>  heading · arc/stage table · closing note          <<<END SUMMARY>>>
```

The parser is the contract. Rules: exactly `count` script blocks or the plan is a
**failure** (never render one clip when six were asked); a marker-less reply with
`count = 1` is accepted as the single script (the older single-paragraph skills);
titles and summary are optional but captured when present — the first title
names the run.

### Frame arithmetic (from STORY_024 / EPIC_001)

```
clip 1   image seed  → frames_for(L, "image") = snap4k1(L·24)        L=10 → 241
clip n≥2 video seed  → frames_for(L, "video") = snap4k1(73 + L·24)   L=10 → 313
                        73 = condition_seconds 3.0 · prefix trimmed after caching
```

Every clip is `Length` seconds of new footage; the finished run is `count × L` seconds
of clean, concatenable clips.

### Time and the memory gate

| Size | Clip 1 (I2V, 241) | Each extend (313) | 3 clips | 6 clips |
|---|---|---|---|---|
| 832×480 | ~20 min | ~26 min | ~72 min | **~2.5 h** |
| 704×1280 | ~56 min | ~80 min | ~3.6 h | **~7.6 h** |

Default size for agent runs is **832×480** — this is why the pipeline renders
480p and upscales. The executor checks the memory gate (≥ 30 GiB available, no
NVRM OOM today — `scripts/flow_e2e_renders.sh` has the check) **before every
clip submission** and pauses the run with a stated reason rather than
submitting into a saturated box. The manual loop never had that.

### Runs are durable

A run is a JSON document under `FLOW_MEDIA_DIR/flow-runs/<id>.json` holding: project,
seed, skill, count, length, size, the scripts (with edit history), titles,
summary, state, the clip list (job id → media id), timestamps, and the last
error. The executor is a background task in the sidecar; on start-up it
reloads `rendering` runs and resumes by polling the current clip's job. If the
gateway no longer knows the job (engine restart), the clip is marked failed
and the run stops at that clip with **Resume from clip n** available.

### Gemma from the sidecar

The gateway's upsampler already talks to Ollama on the host; the sidecar gets
the same `extra_hosts` mapping and `GEMMA_URL`. The planner uses the native
`/api/chat` with the seed as a base64 image and `options.num_ctx` pinned to
**32768**: measured 2026-09-07, the default 262k context made the same
10k-token prompt take 219 s against 102 s at 32k, and the oversized KV cache
costs memory the box does not have. Retries follow STORY_022: content
failures (wrong script count, unparsable blocks, empty content) retry
immediately, up to 5 attempts, then the plan fails loudly.

### Nothing in the request contract moves

Each clip is `POST :8002/generate` with `image=` (clip 1) or `video=` +
`condition_seconds=3.0` (clips 2..N), `upsample=true`, the script as `prompt`.
The gateway upsamples per clip exactly as it does for a manual generate.
`gateway/server.py` is untouched; the agent is a client of the gateway.

---

## Stories

| # | Story | Delivers |
|---|---|---|
| **029** | The agent writes the scripts | `data/prompts/` library + frontmatter contract; `GET /agent/instructions`; `POST /agent/plan` (seed, skill, count) → scripts/titles/summary via Gemma with count validation and retries; the parser; `num_ctx` pin; sidecar reaches Ollama |
| **030** | The agent renders the plan clip by clip | Durable runs; review state (edit, rewrite one script, approve); the executor: I2V then Extend ×(N−1), memory gate per clip, step labels, resume; `POST /agent/runs`, `GET /agent/runs`, `GET /agent/runs/{id}`, `POST /agent/runs/{id}/approve`; clips land in `flow-outputs` and the picker |
| **031** | Run a scene from the terminal, gated or zero-shot | `scripts/flow_agent.sh plan|approve|status|watch`; the confirm setting (Always/Never) as a per-run `autostart`; one real **3-clip run at 480p** on the box as E2E (~72 min, behind the memory gate) |
| **032** | The Agent pill works in the Flow UI | The `FLOW_VERSION` bump that lands the upstream Agent UI; contract + conformance; the UI drives the same routes the CLI does |

The **Agent UI** itself is flow-repo work — an additive protocol surface
(`capabilities.agent`, `/flow/agent/*` mirroring the routes above), the pill's
ON state (RECON-04 §7), an instructions picker, a settings panel, the review
view, and step labels on the run's tiles. Scoped in the flow repo as its own
epic after STORY_030 proves the server side; STORY_032 here is its landing.

## Known limitations (documented, not fixed by this epic)

1. **One run renders at a time.** A second run waits in `queued` until the first finishes or fails.
2. **A run's seed must be 24 fps if it is a video** — inherited from EPIC_001. Our own outputs always qualify.
3. **No concatenation.** The run produces N clean 10 s clips; joining them is the pipeline's job today.
4. **Rewrite regenerates one script in isolation.** It sees the seed, the skill, the position (clip n of N) and the neighbouring scripts, but the summary and titles are not regenerated — they can drift from a heavily rewritten plan.
5. **The plan is only as good as the skill.** The agent enforces the count and the markers; it does not judge script quality.

## Definition of Done

- [ ] `data/prompts/` holds Kevin's skills and the UI/CLI lists them by frontmatter name
- [ ] `POST /agent/plan` returns exactly `count` scripts for every skill that carries `{{COUNT}}`, and one script for those that do not; a wrong count fails after retries, never renders
- [ ] A run survives a sidecar restart mid-chain and resumes on the same clip
- [ ] A 3-clip 480p run completes end to end on the box: three clean 10 s clips in the picker, each clip's tile showing the script and the upsampled prompt
- [ ] Confirm-before-render is Always by default and a zero-shot run is possible with it off
- [ ] The memory gate pauses a run instead of submitting into a saturated box, and says so
- [ ] `gateway/server.py` unchanged across the epic
- [ ] Every story ships unit + integration + e2e tests; `flow/` stays ≥ 95 % coverage
