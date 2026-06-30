# spark-cosmos3

NVIDIA **Cosmos 3 Nano** (text/image-to-video with audio) served as an HTTP
API on a **DGX Spark** (GB10 Grace Blackwell, ARM64/aarch64, ~128 GB unified
memory), fully containerized with Docker.

This repo captures a working deployment for reproducibility. **Model weights
are NOT in this repo** (~33 GB) — see [Download the weights](#2-download-the-weights).

## Architecture

There is **no custom server code**. The HTTP API is
[vLLM-omni](https://hub.docker.com/r/vllm/vllm-omni)'s built-in OpenAI-style
`/v1/videos` endpoint, served directly by the upstream `vllm/vllm-omni:cosmos3`
image (linux/arm64, CUDA 13.0.2 — required for the GB10; standard x86 PyPI
wheels do not work on this machine). The image is pinned by digest in
[docker-compose.yml](docker-compose.yml).

```
client ──POST /generate──▶ cosmos3-gateway :8002 ──▶ cosmos3-api :8000 (vllm serve)
       ◀─poll /jobs/{id} (real progress merged)─┐         │
                                                └── cosmos3-progress :8001
                                                    (parses denoise tqdm from logs)

volumes:  ~/.cache/huggingface  → /root/.cache/huggingface   (weights)
          ~/Documents/cosmos-media → /media                  (input images)
          ./data → /data (gateway, ro)                       (neg.json, audio.txt)
```

**Clients should call the gateway (:8002), not vLLM-Omni directly.** The
gateway owns the request contract: it applies the benchmark-tuned negative
prompt, the audio house style, the Table 21 sampling params, and the correct
field names — clients send only creative intent (image, prompt, size,
frames, steps, sound on/off). Its `/jobs/{id}` also merges **real** per-step
progress from the log-parsing sidecar (vLLM-Omni's own `progress` field is
static during generation).

| | |
|---|---|
| Model | `nvidia/Cosmos3-Nano`, served from `…/snapshots/main` in the HF cache |
| Pipeline class | `Cosmos3OmniDiffusersPipeline` (`--omni` mode) |
| Port | 8000 |
| Init timeout | 1800 s (model load takes several minutes) |

## Quick start

### 1. Clone & configure

```bash
git clone https://github.com/kevinbrowncodes/spark-cosmos3.git
cd spark-cosmos3
cp .env.example .env   # set HF_TOKEN (never committed)
```

### 2. Download the weights

Accept the license for `nvidia/Cosmos3-Nano` on huggingface.co first, then:

```bash
./scripts/download_models.sh
```

This places ~33 GB at
`~/.cache/huggingface/hub/models--nvidia--Cosmos3-Nano/snapshots/main/`.
Note the **non-standard `snapshots/main` layout** (plain files, not the usual
commit-hash snapshot) — the serve command points at this exact path.

### 3. Run

```bash
./scripts/deploy.sh
docker compose logs -f     # wait for "Application startup complete"
curl http://localhost:8002/health
```

`deploy.sh` builds the gateway and progress-sidecar images with the current git
commit SHA baked in as a Docker label, then starts the full stack. Use this
instead of bare `docker compose up -d` so you always know what code is running.

## API usage

See [examples/generate.sh](examples/generate.sh) for a complete
submit/poll/download client. Requests are **multipart form-data** (all values
strings), with the input image as the `input_reference` file part.

### Production generation parameters

From the Cosmos Technical Report, Table 21 (Cosmos3-Nano audio-visual):

| Field | Value | Notes |
|---|---|---|
| `num_inference_steps` | `50` | ~50–57 min per clip on the GB10; use 4 for smoke tests |
| `guidance_scale` | `6.0` | |
| `flow_shift` | `10.0` | |
| `size` | `720x1280` | vertical |
| `fps` | `24` | |
| `num_frames` | 5–300 | e.g. 189 ≈ 7.9 s |
| `max_sequence_length` | `4096` | |
| `generate_sound` | `true` | ⚠️ NOT `enable_audio` — common mistake |
| `sound_duration` | `num_frames / fps` | seconds, as a string |
| `negative_prompt` | contents of [data/neg.json](data/neg.json) | official Cosmos Appendix B.6 structure |
| `extra_params` | `{"guardrails": false, "use_resolution_template": false, "use_duration_template": false}` | JSON string; disables guardrails/face-blur and resolution/duration templates so explicit size/frames are honoured |

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/videos` | submit job → `{"id": …}` |
| GET | `/v1/videos/{id}` | poll → `{"status": queued\|in_progress\|completed\|failed, "progress": %}` |
| GET | `/v1/videos/{id}/content` | download the MP4 |
| GET | `/health` | liveness |

## Repo layout

```
docker-compose.yml          # the deployment — pinned upstream image + serve command
gateway/                    # canonical request layer on :8002 — call this, not :8000
progress-sidecar/           # serves real per-step progress on :8001 (vLLM-Omni's progress field is static)
.env.example                # HF_TOKEN and path overrides (copy to .env)
data/neg.json               # negative prompt (Cosmos Appendix B.6) — CANONICAL copy
data/audio.txt              # constant audio directive: ambient only, no dialogue
scripts/deploy.sh           # build images (with git SHA label) and start the full stack
scripts/download_models.sh  # re-fetch the 33 GB weights into the expected layout
scripts/sync_config.sh      # deploy data/* to the runtime location (cosmos-media)
scripts/export_secrets.sh   # (Spark 1) print HF_TOKEN + ANTHROPIC_API_KEY for transfer
scripts/import_secrets.sh   # (Spark 2) pull secrets from Spark 1 via SSH into .env
examples/generate.sh        # curl-based submit/poll/download client
CLAUDE.md                   # operational context for Claude Code sessions
docs/api.md                 # full /v1/videos parameter reference (from OpenAPI + source)
docs/responses.md           # real captured API payloads
docs/spark-notes.md         # GB10 unified-memory quirks and runbook
docs/container.md           # the vllm-omni image: lineage, versions, runtime flags
docs/prompting.md           # the structured prompt format Cosmos was trained on
docs/cosmos-framework.md    # survey of NVIDIA's native train/serve stack (unused here)
docs/cosmos-3-technical-report.md  # full technical report as markdown (PDF is local-only)
docs/cosmos-3-quick-reference.md   # deployment-focused summary of the report
```

## Further reading

- [Cosmos 3 technical report](https://arxiv.org/abs/2606.02800) — sampling
  params (Table 21), negative prompt structure (Appendix B.6).
  [PDF](https://research.nvidia.com/labs/cosmos-lab/cosmos3/technical-report.pdf)
- [vLLM-Omni docs](https://docs.vllm.ai/projects/vllm-omni/en/stable/) and
  [video API internals](https://deepwiki.com/vllm-project/vllm-omni/6.3-image-and-video-generation-apis)
- [NVIDIA cosmos cookbook](https://github.com/nvidia/cosmos) — inference
  benchmarks and recipes
- [nvidia/Cosmos3-Nano model card](https://huggingface.co/nvidia/Cosmos3-Nano)

## Multi-Spark setup

To bring up a second Spark using the same stack:

```bash
# On Spark 2 — clone, pull secrets from Spark 1, sync config, transfer weights
git clone https://github.com/kevinbrowncodes/spark-cosmos3
cd spark-cosmos3
./scripts/import_secrets.sh          # SSHes to Spark 1 (default 192.168.1.33) and writes .env
mkdir -p ~/Documents/cosmos-media
./scripts/sync_config.sh
# Two models are required: the main weights and the guardrail safety model
rsync -avP --mkpath \
  kevinbrown@192.168.1.33:~/.cache/huggingface/hub/models--nvidia--Cosmos3-Nano/ \
  ~/.cache/huggingface/hub/models--nvidia--Cosmos3-Nano/
rsync -avP --mkpath \
  kevinbrown@192.168.1.33:~/.cache/huggingface/hub/models--nvidia--Cosmos-1.0-Guardrail/ \
  ~/.cache/huggingface/hub/models--nvidia--Cosmos-1.0-Guardrail/
rsync -avP --mkpath \
  kevinbrown@192.168.1.33:~/.cache/huggingface/hub/models--Qwen--Qwen3Guard-Gen-0.6B/ \
  ~/.cache/huggingface/hub/models--Qwen--Qwen3Guard-Gen-0.6B/
./scripts/deploy.sh
```

**Verifying both Sparks are on the same code:**

```bash
docker inspect spark-cosmos3-gateway:latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Labels'])"
```

Run this on each machine — `git.sha` should match. The engine image
(`vllm/vllm-omni:cosmos3`) is pinned by digest in `docker-compose.yml` and is
always identical regardless of when it was pulled.

## Troubleshooting

- **Exit code 137** — OOM kill. The GB10's unified memory is shared with
  everything else on the Spark; stop other heavy containers before loading.
- **Slow startup is normal** — weight loading takes minutes; that's what
  `--init-timeout 1800` is for. Watch `docker compose logs -f`.
- **Weights not found** — the serve path is hardcoded to
  `snapshots/main`; a stock `hf download` (commit-hash snapshot) won't match.
  Use `scripts/download_models.sh`.
- **Audio missing** — you sent `enable_audio`. The field is `generate_sound`
  (plus `sound_duration`).

## Rules of the repo

- **Never commit weights** — `.gitignore` blocks `*.safetensors` and friends;
  verify with `git status` before every commit.
- **Never commit `.env` or tokens.**
- Docker only — no bare-metal/venv deployments on the Spark.
