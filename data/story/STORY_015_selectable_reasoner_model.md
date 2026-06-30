# STORY_015 — Let the pipeline choose which AI model rewrites the prompt

As a pipeline operator, I want to specify whether the gateway should use Anthropic Opus or the local AEON model to upsample the generation prompt, so I can use the uncensored local model when content policies would otherwise block or degrade the rewrite.

## Acceptance Criteria

- [ ] `POST /generate` accepts an optional `reasoner` field (string, default `"opus"`)
- [ ] `reasoner=opus` routes to the existing Anthropic Opus upsampler — identical to current behaviour; clients that omit the field are unaffected
- [ ] `reasoner=aeon` routes to the AEON vLLM endpoint configured via `AEON_URL` in `.env`
- [ ] Sending an unrecognised `reasoner` value returns HTTP 422 with a clear error listing accepted values (`["opus", "aeon"]`)
- [ ] The `reasoner` value used is recorded in the job's provenance block (alongside `prompt_source`, `upsample_attempts`, etc.)
- [ ] If `reasoner=aeon` is selected but the AEON endpoint is unreachable, the gateway returns HTTP 503 — it does **not** silently fall back to Opus (the operator chose AEON deliberately)
- [ ] `.env.example` documents the `AEON_URL` variable

## Technical Notes

### Architecture

- **Spark 1** (192.168.1.33): runs AEON (`aeon-ultimate-xs` container, port 8003), Cosmos stopped
- **Spark 2** (192.168.1.37): runs Cosmos + this gateway; when `reasoner=aeon`, the gateway calls Spark 1's AEON over the LAN for upsampling, then generates locally

### AEON endpoint

- URL: `${AEON_URL}/v1/chat/completions` — standard OpenAI-compat chat completions
- Default value for `AEON_URL`: `http://192.168.1.33:8003`
- Model name to send in the request body: `aeon-ultimate`
- Add `AEON_URL` to `.env` and `.env.example` (not hardcoded in code)

### Implementation

- New field `reasoner` added to the gateway's `GenerateRequest` form model alongside existing fields
- The upsampler module (`gateway/upsampler.py`) gets a second code path for AEON using `httpx.AsyncClient` to call the OpenAI-compat endpoint — same prompt/schema sent as Opus, same structured JSON output expected
- Both paths share the retry logic from STORY_014 (3 attempts, fixed 30s delay on transient errors)
- `reasoner` is validated at the form-parse layer; unrecognised values are rejected before any generation work starts
- The 503 on AEON unreachable should be a connection error caught at the first attempt (no retry on connection refused — the host is either up or it isn't)

## Testing Plan

- **Unit** — mock both upsampler backends:
  - Omit `reasoner` → Opus path called, AEON path never called
  - `reasoner=opus` → Opus path called
  - `reasoner=aeon` → AEON path called with correct URL and model name, Opus never called
  - `reasoner=unknown` → HTTP 422 returned, no generation started
  - `reasoner=aeon` + AEON endpoint returns connection refused → HTTP 503, no Opus fallback
  - Provenance block contains `reasoner: "aeon"` when AEON path is used
- **Contract** — curl tests against a running gateway:
  - Omitting `reasoner` still returns a job ID (backward-compat)
  - `reasoner=badvalue` returns 422
  - `reasoner=aeon` with AEON unreachable returns 503 (not 500, not a fallback job)
- **Smoke** — not required; only the upsampler routing changes, not the generation path

## Estimated Complexity

Small-medium — new field, new code path in the upsampler, `AEON_URL` env var, unit test coverage for both paths. No docker-compose or schema changes.
