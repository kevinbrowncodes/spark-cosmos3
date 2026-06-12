# cosmos-framework — the other official path (survey)

What [github.com/nvidia/cosmos-framework](https://github.com/nvidia/cosmos-framework)
is and when we'd reach for it. **We do not run it** — our serving path is
vLLM-Omni (see docs/container.md). This is a map, not a runbook.

## What it is

NVIDIA's end-to-end framework for **training and serving** Cosmos world
models — the native PyTorch stack, entrypoint
`python -m cosmos_framework.scripts.inference`. Capabilities (from the repo
and the cookbook's `run_with_cosmos_framework` notebooks):

- Inference backends: Diffusers, Transformers, vLLM
- Distributed training: FSDP / TP / CP / PP
- Offline batch generation; online serving via Ray + Gradio
- Dataset adapters: JSONL, WebDataset, LeRobot (robotics)
- Policy Server for robotics/action deployment

License: released with the Cosmos project (OpenMDW-1.1 per the technical
report). Install is `uv`-based (needs `uv ≥ 0.11.3`, dependency groups
`cu130-train` / `cu128-train`); a Dockerfile exists but it is not
Docker-first. Reference hardware: 8× H100 80 GB.

## vLLM-Omni vs cosmos-framework — when to use which

| Need | Use |
|---|---|
| HTTP API serving Cosmos3-Nano generation (our case) | **vLLM-Omni** (what we run; the cookbook's recommended Docker path) |
| Fine-tuning / post-training on our own data | cosmos-framework (only official trainer) |
| Action/policy modes for robotics (LeRobot data, policy server) | cosmos-framework |
| Offline batch generation of many clips without an API | cosmos-framework, or just script against our API |
| Research-style runs with native checkpoints / Diffusers | cosmos-framework |

## Caveats for the Spark specifically

- It expects `uv`-managed Python envs — conflicts with our Docker-only rule.
  If we ever adopt it, build its Dockerfile (arm64 support **unverified**).
- Training reference is 8× H100; meaningful fine-tuning of a 16B model on a
  single GB10 with 121 GiB unified memory is unrealistic. Treat
  fine-tuning as a cloud/DGX job, with the Spark serving the result.
- For pure serving there is no reason to switch: vLLM-Omni is the path NVIDIA
  recommends in the cookbook for API workloads, and it's what the
  `/v1/videos` contract (and our pipeline) is built on.

## Local resources

- Cookbook notebooks (local clone `~/cosmos/cookbooks/cosmos3/`):
  `generator/audiovisual/run_with_cosmos_framework.ipynb`,
  `generator/action/run_*_with_cosmos_framework.*`
- Related repos: [nvidia/cosmos](https://github.com/nvidia/cosmos) (cookbook),
  [vllm-project/vllm-omni](https://github.com/vllm-project/vllm-omni) (our server)
