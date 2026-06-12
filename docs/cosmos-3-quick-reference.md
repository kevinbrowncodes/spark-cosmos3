# Cosmos 3 Technical Report — distilled reference

Source: *Cosmos 3: Omnimodal World Models for Physical AI*, NVIDIA, 2026-06-01
([arXiv:2606.02800](https://arxiv.org/abs/2606.02800) ·
[PDF](https://research.nvidia.com/labs/cosmos-lab/cosmos3/technical-report.pdf) ·
local copy: `docs/cosmos-3-technical-report.pdf`, 138 pp, kept out of git).
Full text as searchable markdown: `docs/cosmos-3-technical-report.md`.

This file extracts what matters for **our deployment** (Cosmos3-Nano,
audio-visual image-to-video via vLLM-Omni) and indexes the rest by page.

## Model family (§2.5, p. 14)

| Variant | Total params | Dense transformer | LLM base | Status |
|---|---|---|---|---|
| Cosmos3-Edge | 4B | 2B (from scratch) | Qwen3-1.7B-like | later release |
| **Cosmos3-Nano** (ours) | **16B** | 8B | Qwen3-VL 8B | released |
| Cosmos3-Super | 64B | 32B | Qwen3-VL 32B | released |

All variants are dual-tower Mixture-of-Transformers (MoT): a reasoner tower
and a generator tower with joint attention, initialized from pre-trained VLMs.
One model handles language, image, video, audio, and action jointly.

## Generation envelope (§6.3.1, p. 72)

The generator supports: **10–30 fps**, **5–400 frames**, resolutions
**256p / 480p / 720p**, aspect ratios **1:1, 3:4, 4:3, 9:16, 16:9**.
(Our vLLM-Omni deployment clamps frames to 5–300 and we run 720p 9:16.)

## Table 21 — default sampling configs (p. 73, verbatim)

| Model | Modality | Sampling | Negative prompt |
|---|---|---|---|
| **Cosmos3-Nano** | **Audio-Visual** | **steps=50, guidance=6, shift=10, full-range CFG** | **Appendix B.6** |
| Cosmos3-Super | Audio-Visual | steps=50, guidance=6, shift=10, full-range CFG | Appendix B.6 |
| Cosmos3-Super-Text2Image | Visual | steps=50, guidance=4, shift=3, full-range CFG | Null |
| Cosmos3-Super-Image2Video | Visual | steps=50, guidance=6, shift=5, full-range CFG | Appendix B.3 (derived from user prompt) |
| Cosmos3-Nano / Super | Forward/Inverse Dynamics | steps=50, guidance=1, shift=5, full-range CFG | Null |
| Cosmos3-Nano-Policy-DROID | Policy | steps=4, guidance=3, shift=5, full-range CFG | Null |
| Cosmos3-Nano / Super | Transfer | steps=50, guidance=3, control guidance=1.5, shift=10 | Appendix B.6 |

The bolded row is our production config — `num_inference_steps=50`,
`guidance_scale=6.0`, `flow_shift=10.0` in the API. "Time shift" in the paper
= `flow_shift` in vLLM-Omni.

## Negative prompt (§6.3.1 p. 72, Appendix B.6 pp. 90–92)

NVIDIA tuned negative prompts per model/mode by automated benchmark ablation
(candidates: natural language, keyword lists, directives, physical-consistency
extensions, null string). For base Nano/Super audio-visual, the winner is the
explicit structured prompt in Appendix B.6 — a JSON-style document with
`subjects` (3 variants of degraded-subject descriptions, each with
appearance/relationship/location/pose/action/state_changes/clothing/expression
fields), plus `background_setting`, `lighting`, `aesthetics`,
`cinematography`.

**Our `config/neg.json` is this Appendix B.6 prompt** — verified structurally
identical (same 5 top-level keys, 3 subject entries, matching text).
Takeaways: don't hand-edit it (it's benchmark-tuned, not prose), and don't
assume it transfers to other Cosmos variants (Super-I2V and action modes use
different/null negative prompts).

## Prompting guide (§6.3.1, pp. 72–73; schema Appendix A, pp. 80–83)

- The generator is trained on **structured JSON captions**: subjects,
  background, lighting, aesthetics, cinematography, and temporal fields
  (actions, state changes, camera motion, segment descriptions).
- NVIDIA's reference stack runs a **prompt upsampler** (Claude Opus 4.6 or the
  Cosmos 3 Reasoner) that expands a short user request into that structured
  format before generation — prompts matching the training distribution
  generate better. Upsampler templates: Appendix B.1 (pp. 84–86).
  Our pipeline writes dense prose prompts directly; adopting the structured
  JSON format (Appendix A schema) is a documented upgrade path.
- Media controls (duration, fps, height/width, aspect ratio) are explicit
  request fields, not prompt text — consistent with our client disabling
  `use_resolution_template`/`use_duration_template`.

## Serving (§5.3.3, p. 48)

vLLM-Omni is NVIDIA's documented inference framework for the generator —
our deployment is the reference path, not a community hack.

## Page index (for targeted reading of the local PDF)

| Pages | Content |
|---|---|
| 5–6 | Introduction |
| 7–14 | Architecture: encoders, token arrangement, MoT, position embeddings, variants |
| 14–25 | Data (reasoner + generator, incl. audio §3.2.2 p. 23) |
| 26–31 | Training (pre/mid/post-training per mode) |
| 32–49 | Infrastructure (data, training, serving §5.3 pp. 45–49) |
| 50–71 | Results: image/video/audio/transfer/action evaluations |
| 72–74 | **Generator User Guide** (the operationally important part) |
| 75–79 | Related work, conclusion |
| 80–83 | Appendix A: caption JSON schemas (image, video) |
| 84–95 | Appendix B: upsampler templates, **B.6 negative prompt (90–92)** |
| 96+ | Appendix C+: synthetic training datasets |
