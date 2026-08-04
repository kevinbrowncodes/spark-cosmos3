# STORY_022 — The gateway upsamples with the local model by default

**Epic:** EPIC_001 — Continue an existing video clip
**Depends on:** STORY_019 (V2V upsampler contract), STORY_015 (reasoner selector)
**Unblocks:** STORY_019 sign-off

As a pipeline operator, I want the gateway to upsample prompts using the local
Gemma model by default, so that `upsample=true` produces a structured prompt
without an API key, without a remote service, and without silently falling back
to prose.

## Acceptance Criteria

- [ ] `gemma` is a valid reasoner and is the **default** — a request with no `reasoner` field uses it
- [ ] `opus` and `aeon` remain selectable, unchanged in behaviour
- [ ] The gateway reaches Ollama from inside its container (it currently binds loopback)
- [ ] Gemma's ~11% JSON-syntax failure rate is absorbed by retries, matching the STORY_014 treatment of the Opus path
- [ ] A malformed response after all retries falls back to prose and reports `upsample_fallback_reason`, never a 500
- [ ] The V2V path sends **labelled stills** from the conditioning window, exactly as STORY_019 specifies
- [ ] `upsampler_output` echoes the structured prompt per the STORY_016 contract
- [ ] Output is validated against the canonical 18-key set before use — no extra keys, no missing keys, non-empty `temporal_caption` and `audio_description`
- [ ] Gemma is **not left resident** after upsampling (see Technical Notes — this has already cost a scheduling abort and paged the engine to swap)
- [ ] `docs/api.md` documents the default and the reasoner options

## Technical Notes

**Why this story exists.** Every upsampled prompt in QUILL, ANCHOR, REACH, RANGE
and all five production runs came from **scratchpad harness scripts** calling
Ollama directly. The gateway has never known about Gemma —
`_VALID_REASONERS = ("opus", "aeon")`, and zero mentions of gemma/ollama in any
gateway file. So a pipeline request with `upsample=true` today tries Opus (no
key), falls through to prose, and delivers the flat-prose quality that **lost
QUILL 10-1** with nothing in the response to signal it beyond
`upsample_fallback_reason`.

This story moves a proven capability out of throwaway code and into the product.

**Gemma becomes the default because it is the only reasoner that works here.**
Opus needs credit; AEON has been unreachable throughout. Gemma is local, free,
already installed, and its prompts won QUILL decisively. Defaulting to a reasoner
that cannot answer is how the silent prose fallback happened in the first place.

**Implementation is mostly the AEON path.** Ollama is OpenAI-compatible, so
`_upsample_aeon` is the template — same request shape, same `image_url` data-URL
parts, same retry and fallback structure. Differences:

- endpoint `http://<host>:11434/v1/chat/completions`, model `gemma4:26b`
- **thinking tokens count against `max_tokens`.** At 300 the content came back
  *empty* while 447 tokens went to a separate `reasoning` field. Keep 8192 and
  treat empty content as a retryable failure, not a success.
- retries are load-bearing, not defensive: measured ~11% JSON-syntax failure

**Networking.** Ollama binds `127.0.0.1:11434` and `OLLAMA_HOST` is unset, so the
gateway container cannot reach it. Needs `OLLAMA_HOST=0.0.0.0:11434` plus
`extra_hosts: ["host.docker.internal:host-gateway"]` in `docker-compose.yml`.
Overlaps STORY_021; do the minimum here and leave residency to that story.

**Do not leave Gemma resident.** It holds 18 GB and Ollama's default keep-alive is
5 minutes. Measured consequences: a production run aborted on the 30 GiB memory
guard because Gemma was still loaded from the previous run's last upsample, and
co-residency paged 1.75 GiB of the engine to swap. Upsampling happens *before* a
render, so nothing needs it resident during generation.

**Validation must be stricter than the current `"subjects" in d` check.** Gemma
has emitted `scene_imagination` — a key from the report's Appendix B.1 that is
**not** in the vendored schema — which the template forbids. Validate the full
canonical key set both ways.

## Testing Plan

**Unit** (required) — `gateway/tests/test_gemma_reasoner.py`:
- omitting `reasoner` selects gemma; `opus` and `aeon` still route correctly
- an invalid reasoner still 422s
- a malformed JSON response retries, then falls back to prose with a reason
- **empty `content` with a populated `reasoning` field is treated as a failure**, not success
- a response with extra or missing keys is rejected
- V2V sends labelled stills; I2V sends one unlabelled image
- the I2V request shape is unchanged from today (regression guard)

**Contract** (required) — curl against the running gateway:
- `POST /generate` with `upsample=true` and no `reasoner` returns
  `prompt_source: "upsampled"` and a non-null `upsampler_output`
- the same with Ollama stopped falls back to prose and names the reason
- `reasoner=opus` with no key still reports `no_api_key`

**Smoke** (required — the prompt reaching the engine changes): one 480p V2V
render at `frames=313`, `condition_seconds=3.0`, `upsample=true`, no `reasoner`.
Confirm the engine received structured JSON, and that `free -h` shows Gemma
unloaded once the render starts.

## Estimated Complexity

**Medium.** The upsampler change is small and closely modelled on the AEON path.
The work is in the container networking and in tests that pin the failure modes
already observed in practice.
