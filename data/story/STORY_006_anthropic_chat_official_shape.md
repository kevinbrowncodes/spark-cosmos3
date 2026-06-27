# STORY 006 — Send Anthropic Chat with the Official Shape and Sampling Params

As a gateway operator, I want the upsampler API call to match NVIDIA's validated chat shape and sampling config, so that the model receives the image before the text, the correct system prompt, and the same generation parameters the framework uses.

## Acceptance Criteria

- [x] `_detect_media_type` + `_image_block` helpers added; media type detected from magic bytes (JPEG/PNG/WebP), not from file extension or upload Content-Type.
- [x] `_extract_json` replaced: strips ```json fence, `json.loads`, asserts dict, raises `ValueError` on any failure. Caller catches and returns `(None, "upsampler_error")`.
- [x] `upsample()` signature simplified: `image_b64: str` + `image_media_type: str` replaced with `image_bytes: bytes`; encoding and type detection moved into `_image_block`.
- [x] `messages.create()` updated: `system="You are a helpful assistant."` as top-level param; user content is `[image_block, text]` (image first); `temperature=0.7, top_p=0.8, top_k=20, max_tokens=8192`; `thinking` removed.
- [x] `server.py` updated: passes `image_bytes=image_bytes` directly; `base64` import removed.
- [x] All existing fallback paths preserved: no API key → `(None, "no_api_key")`; exception/parse failure → `(None, reason)`.
- [x] `python -m pytest gateway/tests/` passes.

## Technical Notes

- `system=` is a top-level Anthropic SDK parameter, not a messages[] entry — unlike the OpenAI format the framework uses.
- `temperature + top_p + top_k` together matches the framework's `PromptUpsamplerConfig` defaults and is intentional; Anthropic accepts all three.
- Removing `thinking={"type": "adaptive"}` is a deliberate trade-off: lower cost and latency, matches NVIDIA's validated config.
- `image_media_type` is still set in `server.py` for the engine's multipart call — only the upsampler call changes.

## Testing Plan

- **Unit:** tests for `_detect_media_type` (JPEG/PNG/WebP/unknown), `_image_block` structure, and `_extract_json` (valid fence, no fence, invalid JSON, non-dict) — required.
- **Contract:** existing contract tests (test_audio.py) must still pass — they mock `upsampler.upsample` so the signature change must be reflected in the mock.
- **Smoke:** none — generation path unchanged at the engine level.

## Estimated Complexity

S — targeted rewrite of the API call block + helper functions + tests.
