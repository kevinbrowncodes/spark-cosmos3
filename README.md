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
client ──POST /v1/videos──▶ cosmos3-api (vllm serve, port 8000)
       ◀─poll /v1/videos/{id}, download /v1/videos/{id}/content─┘

volumes:  ~/.cache/huggingface  → /root/.cache/huggingface   (weights)
          ~/Documents/cosmos-media → /media                  (inputs, neg.json)
```

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
docker compose up -d
docker compose logs -f     # wait for "Application startup complete"
curl http://localhost:8000/health
```

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
| `negative_prompt` | contents of [config/neg.json](config/neg.json) | official Cosmos Appendix B.6 structure |
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
.env.example                # HF_TOKEN and path overrides (copy to .env)
config/neg.json             # negative prompt (Cosmos Appendix B.6 structure)
scripts/download_models.sh  # re-fetch the 33 GB weights into the expected layout
examples/generate.sh        # curl-based submit/poll/download client
```

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
