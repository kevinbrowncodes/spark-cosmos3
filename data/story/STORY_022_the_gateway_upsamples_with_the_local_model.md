# STORY_022 — The gateway upsamples with the local model, and only that

**Epic:** EPIC_001 — Continue an existing video clip
**Depends on:** STORY_019 (V2V upsampler contract), STORY_015 (reasoner selector)
**Unblocks:** STORY_019 sign-off
**Supersedes:** STORY_015 (selectable reasoner) — see Technical Notes

As a pipeline operator, I want the gateway to upsample prompts using the local
Gemma model by default, so that `upsample=true` produces a structured prompt
without an API key, without a remote service, and without silently falling back
to prose.

## Acceptance Criteria

- [ ] Gemma is the **only** reasoner — a request with no `reasoner` field uses it
- [ ] **`opus` and `aeon` are removed**: their code paths, the `anthropic` dependency, `AEON_URL`, and the Anthropic retry constants all go
- [ ] `reasoner` is still accepted but only `"gemma"` is valid; `opus`/`aeon` return **422 naming the removal**, rather than being silently ignored
- [ ] The gateway reaches Ollama from inside its container (it currently binds loopback)
- [ ] Retries cover **content** failures, not just HTTP errors — a 200 response carrying malformed JSON, a schema violation, or empty content is retried
- [ ] Content retries are **immediate** (no 30 s backoff — there is no rate limit to back off from on a local model)
- [ ] Up to **5 attempts** on the gemma path; the existing 3-attempt / 30 s HTTP policy is unchanged for opus and aeon
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

**Gemma becomes the only reasoner because it is the only one that works here.**
Opus needs credit the account does not have; AEON has been unreachable all week
(`:8003` times out). Gemma is local, free, already installed, and its prompts won
QUILL 10-1. Defaulting to a reasoner that cannot answer is precisely how the
silent prose fallback happened.

**This supersedes STORY_015, and satisfies its original motivation better.**
STORY_015 added the selector so an *uncensored local model* could be chosen "when
content policies would otherwise block or degrade the rewrite" — a real concern
for this project's subject matter. AEON was that escape hatch and it is down.
Gemma is local, has never refused or sanitised the content across every prompt
generated this week, and is now the default rather than an opt-in. The need
STORY_015 addressed is met; the mechanism it built is not needed.

Per CLAUDE.md §10.2, STORY_015's prose stays frozen — this story supersedes it
rather than editing it.

**Deletion scope:** `_upsample_opus` (~111 lines), `_upsample_aeon` (~107 lines),
the `anthropic` import and client, `_RETRYABLE_STATUS`, `_MAX_ATTEMPTS`,
`_RETRY_DELAY`, `AEON_URL`, `_AEON_MODEL`, and `anthropic` from
`gateway/Dockerfile`. Roughly 240 of 603 lines in `upsampler.py`.

**Keep the `reasoner` field, do not drop it.** FastAPI ignores unknown form
fields, so removing the parameter would make `reasoner=opus` *silently* inert —
the same class of failure this story exists to eliminate. Accepting the field and
returning 422 with a message naming the removal tells the caller exactly what
happened. `reasoner` also stays in the job provenance block (STORY_015's last
criterion), now always recording `gemma`.

**Implementation is mostly the AEON path.** Ollama is OpenAI-compatible, so
`_upsample_aeon` is the template — same request shape, same `image_url` data-URL
parts, same retry and fallback structure. Differences:

- endpoint `http://<host>:11434/v1/chat/completions`, model `gemma4:26b`
- **thinking tokens count against `max_tokens`.** At 300 the content came back
  *empty* while 447 tokens went to a separate `reasoning` field. Keep 8192 and
  treat empty content as a retryable failure, not a success.
**The existing retry does not cover Gemma's failure mode.** `_RETRYABLE_STATUS`
is `{429, 500, 502, 503, 529}` — transport errors only. A parse failure returns
immediately:

```python
except (ValueError, json.JSONDecodeError) as exc:
    return None, "upsampler_error", meta      # no retry
```

That is correct for Opus, which returned valid JSON **72 of 72** times in the job
logs. It is wrong for Gemma, which fails with **HTTP 200 carrying malformed
JSON** — roughly 1 in 9, observed repeatedly across prompt generation. Under
today's logic every one of those would fall straight through to prose.

So the gemma path needs retries on:

| failure | seen in practice |
|---|---|
| `JSONDecodeError` | yes, ~11% |
| extra/missing keys (e.g. `scene_imagination`) | yes |
| empty `content` with a populated `reasoning` field | yes, at low `max_tokens` |
| empty `temporal_caption` or `audio_description` | guard against |

**Immediate retry, not backed off.** The 30 s delay exists for API rate limits
(STORY_014). A local model has none, and a malformed generation is resolved by
sampling again — measured: every observed failure succeeded on the next attempt.
5 attempts, no delay.

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
