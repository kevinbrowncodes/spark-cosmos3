# spark-cosmos3 — context for Claude Code

NVIDIA Cosmos 3 Nano video+audio generation, served on a DGX Spark
(GB10 Grace Blackwell, **aarch64**, 121 GiB unified memory).

## Architecture — read this first

- **There is no custom server code in this repo or anywhere else.** The HTTP
  API is vLLM-omni's built-in OpenAI-style video API, served directly by the
  upstream Docker Hub image `vllm/vllm-omni:cosmos3` (pinned by digest in
  docker-compose.yml). Don't go looking for a FastAPI app to edit.
- The canonical *client* lives in a different repo:
  `ogtv-studios/pipeline/cosmos_client.py`.
- Weights: 33 GB at `~/.cache/huggingface/hub/models--nvidia--Cosmos3-Nano/snapshots/main/`
  — note the **non-standard `snapshots/main`** layout (plain files, not a
  commit-hash snapshot). The serve command hardcodes this path.
  `scripts/download_models.sh` reproduces it. **Never commit weights or .env.**

## API gotchas (each of these has cost real debugging time)

- Audio fields are `generate_sound` + `sound_duration` — **NOT `enable_audio`**.
- Requests are **multipart form-data**; every value is a string, image goes in
  the `input_reference` file part. Full parameter reference: `docs/api.md`.
- `extra_params` is a JSON *string*. `{"guardrails": false}` disables the
  cosmos-guardrail text/video safety checks; `use_resolution_template` /
  `use_duration_template` (default true) append "This video is of HxW
  resolution." / duration text to the prompt — the pipeline disables both so
  explicit size/num_frames are honoured.
- The `progress` field in job status can sit at 0 while denoising is clearly
  advancing in the container logs. Trust the logs, not `progress`.

## Memory operations (the #1 operational hazard)

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

## Service management

- Start/stop: `docker compose up -d` / `docker compose down` in this repo.
  Container name: `cosmos3-api`, port 8000. Auto-starts on boot
  (`restart: unless-stopped`).
- LTX (`ltx2-api`, `ltx2-comfyui`) is **opt-in** (`restart: "no"` since
  2026-06-12): start manually from the spark-ltx2 repo when needed.
- Model load takes ~3.5 min; `--init-timeout 1800` covers it. Ready when
  `curl localhost:8000/health` returns 200.

## Performance (measured on this box)

- 50-step 704x1280 clip: ~46 s/step ≈ 40 min denoising, 50–57 min end-to-end.
- Smoke tests: use `num_inference_steps=4`.

## Docs

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
