# BUG 001 — `temperature` deprecated on claude-opus-4-8; upsampler always falls back

**Status:** Resolved

## Summary

Every upsampler call fails with HTTP 400 from the Anthropic API:
`'temperature' is deprecated for this model.`
The gateway falls back to prose on every request.

## Steps to Reproduce

Submit any generation with `upsample=true` while `UPSAMPLER_MODEL=claude-opus-4-8`.

## Expected vs Actual Behaviour

**Expected:** Opus expands the prompt and returns structured JSON.
**Actual:** `api_error: BadRequestError: 400 — temperature is deprecated for this model.`
Gateway falls back to prose; `prompt_source: "prose"`, `upsample_fallback_reason: "api_error: …"`.

## Root Cause

`_SAMPLING_PARAMS` in `upsampler.py` included `temperature=0.7`, `top_p=0.8`, `top_k=20`
transcribed from NVIDIA's `PromptUpsamplerConfig`, which was validated against an earlier
Opus build. `claude-opus-4-8` does not accept these parameters.

## Acceptance Criteria

- [x] `_SAMPLING_PARAMS` reduced to `{"max_tokens": 8192}`; temperature/top_p/top_k removed.
- [x] Upsampler call succeeds and returns structured JSON.
- [x] `docs/prompting.md` note added: NVIDIA's `PromptUpsamplerConfig` sampling params
      (temperature/top_p/top_k) are not applicable to claude-opus-4-8.

## Resolution

Removed `temperature`, `top_p`, and `top_k` from `_SAMPLING_PARAMS` in `gateway/upsampler.py`.
`max_tokens=8192` retained. Model uses its own defaults for sampling, which is appropriate
for a structured-output instruction-following task. The EPIC 001 epic note that
"claude-opus-4-8 is a deliberate upgrade" from the model NVIDIA validated against covers this:
byte-faithful refers to the template + pinning logic, not the sampling config.
