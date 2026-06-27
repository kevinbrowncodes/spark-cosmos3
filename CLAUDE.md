# spark-cosmos3 — context for Claude Code

> **Workflow, conventions, and guardrails** for AI coding assistants working in this repository.

NVIDIA Cosmos 3 Nano video+audio generation, served on a DGX Spark
(GB10 Grace Blackwell, **aarch64**, 121 GiB unified memory).

---

## 1. Project Overview

**spark-cosmos3** is the gateway + config layer for NVIDIA Cosmos 3 Nano video generation on a local DGX Spark. **Primary language: Python.** Clients call `:8002/generate`; the vLLM-omni engine on `:8000` is upstream-only (no custom code).

See **Architecture** below for the full technical picture.

---

## 2. Repo Structure

```
data/          canonical config (neg.json, audio.txt, story/)
docs/          API reference, notes, technical report, bug/, backlog/
gateway/       Python gateway service (server.py — the core of this repo)
progress-sidecar/  log-parsing progress sidecar
scripts/       sync_config.sh, download_models.sh
docker-compose.yml
```

`data/story/` holds all feature story files. `docs/bug/` and `docs/backlog/` hold bug tickets and backlog items.

---

## 3. How Features Are Built (IMPORTANT)

> **No story file → no code. No exceptions.**

1. Every new feature **must have a story file** created in `data/story/` **before any code is written**.
2. Story files follow this format: user story sentence, **Acceptance Criteria** checklist, **Technical Notes**, **Testing Plan**, **Estimated Complexity**.
3. Stories are implemented **one at a time**, with the story file used as the spec.
4. **Never write code for a feature that does not yet have a story file.** If the user requests work without a story, draft the story file first, get approval, then implement.
5. **Every story must include a Testing Plan section** that calls out which test layers apply:
   - **Unit** — pytest tests for gateway logic: prompt assembly, field mapping, job state machine. Default: required for any new helper or transformation.
   - **Contract** — curl/httpx tests against a running gateway verifying request/response shape and field names. Default: required for any new endpoint or field change.
   - **Smoke** — `num_inference_steps=4` end-to-end generation through the full stack. Default: required only when the generation path itself changes.
   - If a layer is not applicable, the Testing Plan must explicitly say so and explain why. **"No tests needed" is not an acceptable answer without justification.**
6. A story is not **Done** until its Testing Plan tests are written, passing locally, and the story's Acceptance Criteria checkboxes are all checked.

---

## 3b. How Bugs Are Tracked

> Bug tickets live in `docs/bug/BUG_NNN_short_slug.md`. Use a **bug ticket** when existing behaviour is broken. Use a **story** when new behaviour is being added.

- Bug numbers are three-digit zero-padded: `BUG_001`, `BUG_002`, …
- Each ticket follows this format: **Summary**, **Steps to Reproduce**, **Expected vs Actual Behaviour**, **Root Cause**, **Acceptance Criteria**
- A bug ticket is not a substitute for a story — once a bug is understood and the fix requires meaningful new code, create a story that references the bug ticket
- Bug tickets are never deleted; mark them resolved by updating the **Status** field to `Resolved` and adding a **Resolution** note at the bottom

---

## 3c. How Backlog Is Tracked

> Backlog items live in `docs/backlog/BACKLOG_NNN_short_slug.md`. Use a **backlog item** for potential work that is not yet clear or prioritized enough for implementation.

- Backlog numbers are three-digit zero-padded: `BACKLOG_001`, `BACKLOG_002`, …
- Backlog items should stay lightweight: summary, user impact, rough scope, dependencies, open questions, and priority
- Do **not** implement directly from backlog items
- Once an item is clear and prioritized, convert it to a `data/story/STORY_NNN_*.md` file before any code is written
- After promotion to story, remove or archive the backlog item and link to the new story

---

## 4. Dev Workflow

- **Always push to `main`** (this is a single-developer ops repo with no staging branch)
- Before touching the gateway, check that no generation is in progress:
  ```bash
  docker logs cosmos3-api --since 10m | tail
  ```
- After modifying `gateway/server.py`, restart the gateway container only (not the engine):
  ```bash
  docker compose up -d --no-deps cosmos3-gateway
  ```
- After modifying anything in `data/`, sync to the runtime location:
  ```bash
  ./scripts/sync_config.sh
  # use --check first to preview drift
  ```
- **Before every commit, all steps must pass in order:**
  1. `./scripts/sync_config.sh --check` — confirm `data/` and runtime copies are in sync
  2. `python -m pytest gateway/tests/` (if tests exist) — unit/contract tests
  3. Smoke curl: `curl -s localhost:8002/health` returns 200
  4. `git commit && git push origin main`
- Always prefer CLI tools (`docker`, `curl`, `git`) over asking the user to do anything manually
- Give a clear summary after making changes — what changed, what commands were run, and what the outcome was

---

## 5. Architecture — read this first

- Three containers (one compose file): `cosmos3-api` (vLLM-omni engine,
  :8000), `cosmos3-gateway` (canonical request layer, :8002 — **clients call
  this**), `cosmos3-progress` (log-parsing progress sidecar, :8001, consumed
  by the gateway).
- **This repo owns the request contract via the gateway** (`gateway/`):
  neg.json + Table 21 params + correct field names are applied server-side
  here. Clients send only image/prompt/size/frames/steps/sound-toggle to
  `POST :8002/generate` and poll `GET :8002/jobs/{id}` (which has *real*
  progress merged from the sidecar). Audio description is owned by the
  upsampler (Opus fills `audio_description` contextually per scene).
- The engine itself has no custom code — it's the upstream Docker Hub image
  `vllm/vllm-omni:cosmos3` (pinned by digest in docker-compose.yml) serving
  vLLM-omni's built-in `/v1/videos` API.
- The canonical *client* lives in a different repo:
  `ogtv-studios/pipeline/cosmos_client.py`.
- **`data/` is canonical config.** The runtime copies the pipeline actually
  reads live in `~/Documents/cosmos-media/` (mounted into the pipeline
  container) — deploy artifacts, not sources. After any change:
  `./scripts/sync_config.sh` (use `--check` to detect drift).
  - `data/neg.json` — negative prompt; NVIDIA benchmark-tuned (Appendix
    B.6), never hand-edit.
  - `data/story/` — feature story files (see Section 3).
- Weights: 33 GB at `~/.cache/huggingface/hub/models--nvidia--Cosmos3-Nano/snapshots/main/`
  — note the **non-standard `snapshots/main`** layout (plain files, not a
  commit-hash snapshot). The serve command hardcodes this path.
  `scripts/download_models.sh` reproduces it. **Never commit weights or .env.**

---

## 6. API Gotchas (each of these has cost real debugging time)

- Audio fields are `generate_sound` + `sound_duration` — **NOT `enable_audio`**.
- Requests are **multipart form-data**; every value is a string, image goes in
  the `input_reference` file part. Full parameter reference: `docs/api.md`.
- `extra_params` is a JSON *string*. `{"guardrails": false}` disables the
  cosmos-guardrail text/video safety checks; `use_resolution_template` /
  `use_duration_template` (default true) append "This video is of HxW
  resolution." / duration text to the prompt — the pipeline disables both so
  explicit size/num_frames are honoured.
- The `progress` field in job status is **never** updated during generation
  (vllm-omni doesn't implement it — verified in source), and the logs give
  **no live per-step signal** either: tqdm draws the denoise bar as one `\r`-
  updated line with no newline until the loop ends, so docker holds it as a
  single start-timestamped record and doesn't surface it (to `docker logs`,
  `--since`, or a streaming follower) until denoise *finishes* — then every
  step flushes at once. `PYTHONUNBUFFERED=1` does **not** fix this (it's
  Python's buffer, not docker's record framing); earlier notes claiming it
  made bars "live" were wrong — what looked live was only the terminal flush.
  The sidecar (`GET :8001/progress`, container `cosmos3-progress`, code in
  `progress-sidecar/`) is therefore a **terminal/tail signal only** (final
  step + `step==total` → VAE/encode tail), not live motion. A moving bar must
  come from an **elapsed-time estimate** (the gateway's job; see docs/api.md).
- **Engine aborts don't stop GPU work.** DELETE on a job removes the record
  but the denoise loop runs to completion, orphaned, blocking the queue
  (measured: a 42-min 720p render completed after its abort). True
  cancellation = `DELETE :8002/jobs/{id}?hard=true`, which restarts the
  engine via the sidecar (~3.5 min reload, wipes queued job records).

---

## 7. Memory Operations (the #1 operational hazard)

Unified memory: CPU+GPU share the 121 GiB. **`docker stats` massively
undercounts** — CUDA allocations don't show in cgroup memory (LTX's ComfyUI
once held ~100 GiB while `docker stats` reported 30 GiB). `nvidia-smi` shows
N/A for memory on GB10. The only trustworthy check is **`free -h`**.

- Cosmos needs ~45 GiB once loaded. Check `free -h` shows ≥50 GiB available
  **before** `docker compose up -d`. Exit code 137 = OOM-killed.
- LTX (`spark-ltx2` repo) and Cosmos can coexist only if the other is idle and
  unloaded. To free an idle ComfyUI without stopping it:
  `curl -X POST http://localhost:8189/free -H 'Content-Type: application/json' -d '{"unload_models": true, "free_memory": true}'`
- vLLM-omni has `/v1/omni/sleep` + `/v1/omni/wakeup` to release/restore GPU
  memory, but they require `--enable-sleep-mode` at startup, which this
  deployment does **not** currently pass.
- Don't start/stop other model containers without asking — generations run
  ~50 min and must not be interrupted. Check activity first:
  `docker logs cosmos3-api --since 10m | tail`.

---

## 8. Service Management

- Start/stop: `docker compose up -d` / `docker compose down` in this repo.
  Container name: `cosmos3-api`, port 8000. Auto-starts on boot
  (`restart: unless-stopped`).
- LTX (`ltx2-api`, `ltx2-comfyui`) is **opt-in** (`restart: "no"` since
  2026-06-12): start manually from the spark-ltx2 repo when needed.
- Model load takes ~3.5 min; `--init-timeout 1800` covers it. Ready when
  `curl localhost:8000/health` returns 200.

---

## 9. Performance (measured on this box)

- 50-step 704x1280 clip: ~46 s/step ≈ 40 min denoising, 50–57 min end-to-end.
- Smoke tests: use `num_inference_steps=4`.

---

## 10. Key Rules

1. **Always read the relevant story file before writing any code.** The story is the spec.
2. **Never modify a story file's content after it has been implemented.** Acceptance criteria checkboxes may be flipped from `[ ]` to `[x]`, but the prose stays frozen. New requirements → new story.
3. **When adding a new story, follow the `STORY_NNN_short_slug.md` naming convention.** Three-digit zero-padded numbers. Snake_case slugs. Story numbers must match the order they will be implemented — lowest number ships first. **The `# STORY_NNN — …` heading must use plain-English titles a non-engineer can understand — no raw function names, no jargon acronyms.**
4. **Never touch the engine container's config or restart it during an active generation.** Check `docker logs cosmos3-api --since 10m | tail` first.
5. **Test one story at a time.** Never implement multiple stories in a single session. Land one, verify it works, then start the next.
6. **Every story ships with tests.** At minimum a contract curl test; see Section 3 for the full testing ladder.
7. **`data/` is source of truth.** Never hand-edit runtime copies in `~/Documents/cosmos-media/`; always edit `data/` and sync.
8. **Never commit weights, `.env`, or any file over ~1 MB** without explicit discussion.

---

## 11. Docs

- `docs/api.md` — full /v1/videos parameter reference (from this server's OpenAPI + source)
- `docs/responses.md` — real captured request/response payloads
- `docs/spark-notes.md` — GB10/unified-memory quirks, runbook
- `docs/container.md` — what the vllm-omni image contains (build lineage,
  package versions, why each runtime flag exists, update procedure)
- `docs/prompting.md` — the structured JSON prompt format the model was
  trained on; how to write prompts today and the upsampler upgrade path
- `docs/cosmos-framework.md` — survey of NVIDIA's native train/serve stack
  (we don't run it; covers when we would)
- `docs/cosmos-3-quick-reference.md` — deployment-focused distillation of the
  technical report: Table 21 params, neg-prompt provenance, model specs,
  page index
- `docs/cosmos-3-technical-report.md` — **full text** of the technical report
  converted to markdown (~535 KB; search this instead of the PDF; figures
  omitted). Source PDF is local-only/gitignored; upstream:
  https://arxiv.org/abs/2606.02800
- `docs/bug/` — bug tickets (`BUG_NNN_short_slug.md`)
- `docs/backlog/` — backlog items (`BACKLOG_NNN_short_slug.md`)

---

## 12. End of Session Checklist

At the end of **every** chat session:

1. **Commit and push all changes.** Stage all modified files, commit with a meaningful message (e.g. `Story 1: gateway returns elapsed-time progress` or `Fix BUG-001: wrong audio field name`), and push to `origin main`.
2. Review the conversation and ask: **"Does anything we discussed or built today require an update to `CLAUDE.md`?"**
   - If **yes** — list the specific changes needed and **ask the user for approval before updating**.
   - If **no** — explicitly state: **"No updates to `CLAUDE.md` needed this session."**
3. Then also ask: **"Does anything we built or discussed today require an update to any `docs/` files?"**
   - Docs should be updated when: a new API field or endpoint is added, a gotcha is discovered, or performance numbers change.
   - If **yes** — list the specific files and sections that need updating and **ask for approval before making changes**.
   - If **no** — explicitly state: **"No updates to docs needed this session."**
