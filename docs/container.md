# The Cosmos Docker container

What `vllm/vllm-omni:cosmos3` is, where it came from, and how we run it.

## Sources

Two kinds of facts in this doc, labeled accordingly:

**Official documentation:**
- NVIDIA cosmos cookbook — [`cookbooks/cosmos3/README.md`](https://github.com/nvidia/cosmos/blob/main/cookbooks/cosmos3/README.md)
  ("vLLM-Omni → Option 1: Docker (recommended)") and
  [`cookbooks/cosmos3/generator/audiovisual/run_with_vllm_omni.ipynb`](https://github.com/nvidia/cosmos/blob/main/cookbooks/cosmos3/generator/audiovisual/run_with_vllm_omni.ipynb).
  This is NVIDIA's documented deployment path for the Cosmos 3 Generator and
  the origin of our serve command. (Local clone: `~/cosmos/cookbooks/cosmos3/`.)
- Docker Hub — [`vllm/vllm-omni` tags](https://hub.docker.com/r/vllm/vllm-omni/tags):
  the official image, published by the vLLM project. Tags `cosmos3`,
  `cosmos3-aarch64` (linux/arm64), `cosmos3-x86_64` (linux/amd64).
- [vllm-project/vllm-omni](https://github.com/vllm-project/vllm-omni) — the
  serving framework. Release 0.22.0 (June 2026) mainlined "Nvidia
  Cosmos3/DreamZero world model support".

**Read from the image/container itself** (primary artifact; reproduce with the
commands shown): build layers via `docker history vllm/vllm-omni:cosmos3
--no-trunc`, metadata via `docker image inspect`, package versions via
`docker exec cosmos3-api pip list`.

## Identity (inspected 2026-06-12)

| | |
|---|---|
| Image | `vllm/vllm-omni:cosmos3` from Docker Hub (official vLLM project image; NVIDIA cookbook's recommended deployment) |
| Our pinned digest | `sha256:88d27796de038d346b125ce1756fa7ed7f15505b1896af8327b41d207290811c` (build dated 2026-05-29) |
| Platform | linux/arm64 (Hub also publishes amd64; compressed ~11.25 GB, ~28.6 GB on disk) |
| Workdir | `/app` |

⚠️ **The `cosmos3` tag is mutable and has already moved upstream** — as of
2026-06-12 Docker Hub shows the tag updated ~13 days ago (arm64 digest
`1d0c1f9a8291…`), newer than our pinned build. Our compose pins the digest, so
we keep running the version we validated until we deliberately upgrade.

## Build lineage (from `docker history`, our pinned build)

Layered on vLLM's official OpenAI-server image, with Cosmos pieces added:

1. **Base: `vllm/vllm-openai:v0.21.0`** — vLLM commit `ad7125a4`, built by
   vLLM's release pipeline ([Buildkite build 1649](https://buildkite.com/vllm/release-v2/builds/1649)).
   Image labels carry `maintainer: NVIDIA CORPORATION`.
2. `apt-get install git jq`
3. **vLLM replaced with a Cosmos3 fork**: `git clone -b mbala/cosmos3-v0.21.0
   https://github.com/MaciejBalaNV/vllm.git`, installed with
   `VLLM_USE_PRECOMPILED=1` (2.1 GB layer). The `vllm` package inside is
   **not stock v0.21.0** — it carries pre-mainline Cosmos3 support. (As of
   vllm-omni 0.22.0 this support is upstream; a future image upgrade should
   drop the fork.)
4. **vllm-omni 0.21.0** installed from source at `/app/vllm-omni` (752 MB) —
   provides `--omni` mode and the `/v1/videos` API.
5. **cosmos-guardrail 0.3.1** (909 MB) — NVIDIA's safety filters (text/video
   safety, face blur). We disable per-request via
   `extra_params={"guardrails": false}`.
6. `ENTRYPOINT []` — the base entrypoint is cleared, so the full
   `vllm serve …` command must be supplied at run time (which is why our
   compose file carries it).

## Software stack inside (verified in the running container)

| Component | Version |
|---|---|
| OS | Ubuntu 22.04.5 LTS |
| Python | 3.12.13 |
| CUDA toolkit | 13.0.2 (nvcc r13.0) |
| torch | 2.11.0+cu130 |
| vllm | 0.21.0 (MaciejBalaNV cosmos3 fork) |
| vllm-omni | 0.21.0 |
| diffusers | 0.38.0 |
| transformers | 5.8.1 |
| cosmos-guardrail | 0.3.1 |
| triton | 3.6.0 |

`TORCH_CUDA_ARCH_LIST=8.0 8.7 8.9 9.0 10.0 11.0 12.0+PTX` covers Blackwell —
what makes this image work on the GB10. Driver requirement ≥535.

## How we run it vs. the official recipe

NVIDIA's cookbook command (cosmos3 README, "Docker Image: Cosmos3-Nano"):

```bash
docker run --runtime nvidia --gpus all \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -v "$(pwd):/workspace" \
  -p 8000:8000 --ipc=host \
  vllm/vllm-omni:cosmos3 \
  vllm serve nvidia/Cosmos3-Nano \
    --omni --model-class-name Cosmos3OmniDiffusersPipeline \
    --allowed-local-media-path / --port 8000 --init-timeout 1800
```

Our docker-compose.yml is this recipe with three deliberate deviations:

| Deviation | Why |
|---|---|
| serve the local snapshot path instead of `nvidia/Cosmos3-Nano` + `TRANSFORMERS_OFFLINE=1` | never hit the Hub at runtime; serve purely from the validated local weights (non-standard `snapshots/main` layout — see scripts/download_models.sh) |
| image pinned by digest | the `cosmos3` tag is mutable (and has moved since we pulled) |
| `-v ~/Documents/cosmos-media:/media` instead of `$(pwd):/workspace` | shared input images / neg.json location used by all Spark services |

Flag meanings (cookbook + vllm-omni docs): `--omni` enables diffusion/omni
serving; `--model-class-name Cosmos3OmniDiffusersPipeline` selects the Cosmos3
pipeline; `--allowed-local-media-path /` lets the API read mounted media;
`--init-timeout 1800` allows for multi-minute model load. `--ipc=host` is in
the official recipe (PyTorch shared memory). The cookbook also documents
Super-only options we don't use: `--tensor-parallel-size`,
`--enable-layerwise-offload`.

## Operational notes (measured on our box)

- Memory once loaded: ~45 GiB unified (OOM runbook: docs/spark-notes.md).
- Startup to `/health` 200: ~3.5 min.
- Logs: `docker logs cosmos3-api -f` — the tqdm denoising bar is more
  trustworthy than the API's `progress` field.
- vllm-omni sleep mode (`/v1/omni/sleep`) requires `--enable-sleep-mode`;
  not currently enabled.

## Upgrading

The likely upgrade path is a newer official image (current `cosmos3` tag, or a
`v0.22.0+` release tag now that Cosmos3 support is mainlined — that would also
shed the vllm fork):

1. `docker buildx imagetools inspect vllm/vllm-omni:cosmos3` — get the new digest.
2. Edit the digest pin in docker-compose.yml, `docker compose up -d`.
3. Smoke test: `examples/generate.sh` with `num_inference_steps=4`.
4. Roll back by restoring the previous digest line if anything regresses
   (the old image stays on disk until pruned).
