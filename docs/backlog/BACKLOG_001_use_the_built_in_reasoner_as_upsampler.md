# BACKLOG_001 — Use Cosmos 3's own built-in reasoner as the prompt upsampler

**Status:** Unverified idea — needs an experiment before it can become a story

## Summary

Cosmos 3 is a Mixture-of-Transformers with **two** parameter sets: a *Reasoner*
tower for understanding and a *Generator* tower for diffusion. The technical
report states the prompt upsampler is served *"either by Claude Opus 4.6 or by
the Cosmos 3 Reasoner"* (line 1934) — so NVIDIA's own reference path uses the
model's own reasoner rather than an external LLM.

We currently upsample with Gemma 4 26B over Ollama. If the Reasoner is reachable,
it would replace that entirely.

## Why it would be worth having

- **No second model.** Gemma is 18 GB and must be loaded and unloaded around every
  render. Co-loading it already caused a scheduling abort and, on 2026-07-28, left
  1.75 GiB of the engine paged to swap. The Reasoner is *already resident*.
- **No API dependency.** Neither Anthropic credit nor AEON.
- **It is the reference implementation** — trained for this exact task, on the
  exact caption format the Generator expects.
- **It may consume video natively.** The V2V upsampler contract describes an
  *attached conditioning video*. We currently approximate that with five sampled
  JPEG stills because Gemma cannot read video (`video.sample_frames`). A VLM
  trained on video would remove that workaround — and the reviewer has already
  seen Gemma describe five stills of a slow shot as "three identical frames",
  which is exactly the weakness stills-as-proxy would have.
- **Reliability.** Gemma fails JSON syntax roughly 1 in 9 and needs retries.

## How it actually works — from the model card (2026-07-29)

**The Reasoner is NOT served by our current engine.** It requires its own vLLM
instance loaded with an architecture override, and a different package
(`vllm-cosmos3`, not `vllm-omni`):

```shell
vllm serve nvidia/Cosmos3-Nano \
  --hf-overrides '{"architectures": ["Cosmos3ReasonerForConditionalGeneration"]}' \
  --tensor-parallel-size 1 --mm-encoder-tp-mode data --async-scheduling \
  --allowed-local-media-path / \
  --media-io-kwargs '{"video": {"num_frames": -1}}' \
  --port 8000
```

Then queried as an ordinary OpenAI chat completion with `image_url` parts.

**Two consequences:**

- **`--media-io-kwargs '{"video": {"num_frames": -1}}'` means it consumes video
  natively.** That removes `video.sample_frames` and the five-stills
  approximation entirely — the weakness that had Gemma calling five samples of a
  slow shot "three identical frames".
- **It is a second full model in memory**, on a different port, alongside the
  generator. Not "already resident" as first assumed. This is STORY_021's
  co-residency problem, heavier than Gemma's 18 GB.

## Also found: NVIDIA ships an official upsampler CLI

`python -m cosmos_framework.inference.prompt_upsampling` takes `--input`,
`--mode` (e.g. `text2video`), `--resolution`, `--aspect-ratio`, and crucially
`--endpoint-url` / `--model` / `--api-token`. We hand-rolled this logic in
`gateway/upsampler.py`.

**Since Ollama is OpenAI-compatible, the official CLI can be pointed at Gemma** —
giving NVIDIA's exact prompt construction with a local model and no Reasoner
server. That is a cheaper experiment than standing up a second vLLM, and worth
trying first.

## Open questions

1. Does a Reasoner server fit in memory beside the generator? Generator peak is
   ~48.5 GiB of 121; a second Cosmos3-Nano load is not free.
2. Does it contend with rendering for the GPU? Upsampling would queue behind
   generation on a single card, which could make it *worse* than Gemma despite
   the memory saving.
3. Does its video input beat five stills in output quality — the thing that
   would actually justify the complexity?

## How to test

Cheapest first:

1. **Point the official CLI at Gemma** (`--endpoint-url http://localhost:11434/v1`).
   No new server, and it validates NVIDIA's prompt construction against our
   hand-rolled version.
2. Only if that is promising, stand up the Reasoner on a **spare port** with the
   generator idle, and measure memory and latency before comparing quality.
3. Then a blind round (**SCRIBE**) in `docs/experiments.md`.

If it wins, promote to a story: add `reasoner=cosmos` alongside `opus` and `aeon`
in STORY_015's selector, which would also unblock STORY_019's sign-off.

## Priority

**Medium.** Nothing is blocked on it — Gemma works well enough that it won QUILL
10-1. But it would remove a whole model, a memory hazard, and a retry path, and it
is the vendor's own recommended architecture.
