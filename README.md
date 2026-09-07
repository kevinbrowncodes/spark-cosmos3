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

## Flow UI

A browser front end for this box, served by the `flow` sidecar on **:8003**
(**`http://spark-1.local:8003/flow/`** from any machine on the LAN; `/ui/` also works). It implements the
[Flow Gateway Protocol](https://github.com/kevinbrowncodes/flow/blob/v0.1.0/protocol/PROTOCOL.md)
and only ever calls the gateway's existing `/generate`, `/jobs/{id}` and
`/jobs/{id}/content` — `gateway/server.py` is untouched. Uploads and cached
finished clips live in `FLOW_MEDIA_DIR` (default `~/Documents/flow-media`).
The container runs as root, so files there are root-owned; prune with `sudo`.
The served index page carries a small `crypto.randomUUID` shim (BUG_005): browsers only
expose it on https/localhost, and the LAN is plain http.
Health check: `curl localhost:8003/flow/capabilities`.
Field mapping and caching rules: `docs/api.md` → *Flow UI sidecar*.

**`FLOW_VERSION`** (`.env`, default `v0.1.0`) pins both the `flow-protocol`
package and the UI bundle to one release tag of the flow repo. To upgrade the UI:

1. bump `FLOW_VERSION` in `.env`
2. rebuild: `./scripts/deploy.sh`
3. re-run conformance: `docker compose exec flow flow-conformance http://localhost:8003`
   (add `--generate --reference <still> --timeout 3600` for one real render)

Nothing else in this repo changes. Tests: `./scripts/dev_env.sh` once, then
`.venv/bin/python -m pytest --cov=flow --cov-fail-under=95`; the same suite
runs inside the image build, so a red suite never becomes an image.
End-to-end renders: `./scripts/flow_e2e_renders.sh [conformance|ui|extend|all]` — refuses to
start unless ≥ 30 GiB is available and today's kernel log has no NVRM out-of-memory line.
**Extend** a clip: open the picker's *Videos* tab, choose a finished output, set Length, Generate —
the sidecar conditions on its last 3 s and serves only the new footage (raw kept in `flow-outputs-raw/`).

### The scene agent (EPIC_003)

A **skill** is one of the prompt files in `data/prompts/` (frontmatter `name` +
`description`; `{{COUNT}}` marks a multi-clip skill). The agent runs one Gemma
call per plan — seed image + skill + count → every script, titles, and the arc
summary — then renders clip 1 from the seed and **extends** it clip by clip on
the last 3 s, server-side and resumable, pausing rather than submitting when
less than `AGENT_MIN_FREE_GIB` (30) is free. Runs live in `flow-media/flow-runs/`.

```bash
scripts/flow_agent.sh skills                                   # what's in data/prompts
scripts/flow_agent.sh plan  photo.jpg example-forecast-scene 3 # dry run: scripts only, nothing rendered
scripts/flow_agent.sh run   photo.jpg example-forecast-scene 3 # plan → review (Always by default)
scripts/flow_agent.sh show  run_…  ·  edit run_… 2  ·  rewrite run_… 3
scripts/flow_agent.sh approve run_…  &&  scripts/flow_agent.sh watch run_…
scripts/flow_agent.sh run photo.jpg example-forecast-scene 6 --zero-shot     # no review, straight to render
```

Defaults are 832×480 and 10 s per clip (`--size`, `--length` to change); a
6-clip scene is ~2.5 h at 480p and ~7.6 h at 720p. Routes: `/agent/*` on the
sidecar — outside the Flow protocol prefix on purpose.

## Repo layout

```
docker-compose.yml          # the deployment — pinned upstream image + serve command
gateway/                    # canonical request layer on :8002 — call this, not :8000
progress-sidecar/           # serves real per-step progress on :8001 (vLLM-Omni's progress field is static)
flow/                       # Flow UI sidecar on :8003 — browser front end, calls the gateway only
.env.example                # HF_TOKEN and path overrides (copy to .env)
data/neg.json               # negative prompt (Cosmos Appendix B.6) — CANONICAL copy
data/audio.txt              # constant audio directive: ambient only, no dialogue
scripts/deploy.sh           # build images (with git SHA label) and start the full stack
scripts/dev_env.sh          # local .venv for the test suite (pins flow-protocol to FLOW_VERSION)
scripts/flow_e2e_renders.sh # the three EPIC_002 renders (conformance, UI, extend), gated on memory
scripts/flow_agent.sh       # the scene agent from a terminal: skills · plan · run · edit · approve · watch
data/prompts/               # agent skills — one prompt file per style, picked per run
scripts/download_models.sh  # re-fetch the 33 GB weights into the expected layout
scripts/sync_config.sh      # deploy data/* to the runtime location (cosmos-media)
scripts/export_secrets.sh   # (Spark 1) print HF_TOKEN + ANTHROPIC_API_KEY for transfer
scripts/import_secrets.sh   # (Spark 2) pull secrets from Spark 1 via SSH into .env
examples/generate.sh        # curl-based submit/poll/download client
CLAUDE.md                   # operational context for Claude Code sessions
docs/story/                 # feature stories — the spec for every change (STORY_NNN)
docs/epic/                  # epics grouping related stories (EPIC_NNN)
docs/bug/                   # bug tickets (BUG_NNN)
docs/backlog/               # unprioritised ideas, promoted to stories before any code
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
