# DGX Spark (GB10) deployment notes

Hard-won operational knowledge for running Cosmos 3 on this box. The Spark is
a GB10 Grace Blackwell: **aarch64**, 121 GiB **unified** CPU+GPU memory.

## Platform constraints

- Images must be **linux/arm64** with CUDA 13 builds. Standard x86 PyPI torch
  wheels do not work — this is why we use the upstream `vllm/vllm-omni:cosmos3`
  Docker Hub image rather than building from an NGC base.
- `nvidia-smi --query-gpu=memory.*` returns **[N/A]** on GB10 — GPU memory is
  just system memory.

## Memory: how to not OOM (exit 137)

Unified memory means every model service competes for the same 121 GiB.
Three rules:

1. **Only `free -h` tells the truth.** `docker stats` reports cgroup memory,
   which misses CUDA allocations. Measured example: `ltx2-comfyui` showed
   29.6 GiB in `docker stats` while actually holding ~100 GiB (stopping it
   took host usage from 103 GiB → 7.9 GiB).
2. **Cosmos needs ~45 GiB resident** once loaded (33 GB weights + runtime).
   Require ≥50 GiB available in `free -h` before `docker compose up -d`.
3. **Exit 137 = OOM-killed.** The kernel may kill a *different* big process
   than the one that allocated last — an OOM can take down a healthy service.

Freeing memory, least → most disruptive:

| Action | Effect |
|---|---|
| `curl -X POST http://localhost:8189/free -H 'Content-Type: application/json' -d '{"unload_models": true, "free_memory": true}'` | ComfyUI unloads models, container stays up, reloads on next job |
| `docker stop ltx2-api ltx2-comfyui` | frees everything LTX holds; restart from spark-ltx2 repo |
| vLLM `/v1/omni/sleep` | would release Cosmos GPU memory in place, but needs `--enable-sleep-mode` added to the serve command first (untested here) |

## Service inventory (as of 2026-06-12)

| Service | Port | Auto-start on boot | Memory when loaded |
|---|---|---|---|
| `cosmos3-api` (this repo) | 8000 | yes (`unless-stopped`) | ~45 GiB, loaded at startup |
| `ltx2-api` + `ltx2-comfyui` (spark-ltx2) | 8090 / 8189 | **no** (opt-in since 2026-06-12) | ~0 at start, up to ~100 GiB after jobs |
| `comfyui` (sparkyui) | 8188 | yes | small until used |
| `ogtv-pipeline` (ogtv-studios) | 7860 | yes | small; it's the client of Cosmos/LTX |

Cosmos loads all weights at startup (~3.5 min, ~45 GiB immediately).
ComfyUI-based services start empty and balloon on first job. Plan boot-time
memory accordingly.

## Measured performance

- Model load to `/health` 200: **~3.5 min**
- Denoising: **~46 s/step** at 704x1280, 50 steps ≈ 40 min (50–57 min
  end-to-end including VAE/audio/encode)
- NVIDIA's own numbers: `inference_benchmarks.md` in their cosmos cookbook
  repo (https://github.com/nvidia/cosmos — local clone at `~/cosmos`)

## Watching a generation

```bash
docker logs cosmos3-api --since 10m -f   # tqdm: "N/50 [..s/it]"
free -h                                   # memory headroom
```

Don't restart or stop model containers while a tqdm progress bar is moving —
clips take ~50 min and there is no resume.
