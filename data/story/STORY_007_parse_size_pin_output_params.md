# STORY 007 — Wire _parse_size, _pin_output_params, and the Official Template End-to-End

As a gateway operator, I want `upsample()` to use the official template-based prompt and pin the four output params from the canonical resolution dict, so that every request produces a byte-faithful NVIDIA-format caption with deterministic size/duration fields.

## Acceptance Criteria

- [x] `_ALLOWED_DURATIONS` frozenset (`'2s'`–`'10s'`) defined; duration out of range → `ValueError`.
- [x] `_parse_size(size, num_frames, fps)` → `(tier, aspect_ratio, duration_label)` via RRD reverse-lookup; raises `ValueError` on unsupported size or out-of-range duration.
- [x] `_parse_size("720x1280", 189, 24)` → `("720", "9,16", "7s")`.
- [x] `_parse_size("720x1280", 300, 24)` → `ValueError` (duration `"12s"` outside schema enum).
- [x] `_pin_output_params` overwrites `resolution {H, W}`, `aspect_ratio`, `duration`, `fps` from RRD; `duration` is the same string passed from `_parse_size` (single source of truth).
- [x] `upsample()` signature simplified to `(prompt, image_bytes, size, num_frames, fps, generate_sound)` — `width`, `height`, and `audio_style` removed.
- [x] `upsample()` uses `build_upsampler_prompt` (Story 5); old `build_user_text`, `_OUTPUT_TEMPLATE`, `_duration_mss`, `_aspect` removed.
- [x] Caption serialised with `ensure_ascii=True`.
- [x] `invalid_size` fallback reason → HTTP 400 in `server.py` (not prose fallback).
- [x] Sanity check updated from `"scene_imagination"` (old schema) to `"subjects"` (official schema key).
- [x] `python -m pytest gateway/tests/` passes.

## Technical Notes

- `_parse_size` is called before the Anthropic API call — the 400 fires without spending API tokens.
- `_pin_output_params` receives `duration` from `_parse_size`; it must not re-derive it.
- `generate_sound=False` pins `audio_description = ""` after `_pin_output_params` (not inside it — the framework function doesn't handle audio).
- The official schema has no `scene_imagination` key; the sanity check must use a key that is actually in the schema (`subjects` is the first key).

## Testing Plan

- **Unit:** `_parse_size` canonical path, unsupported size, out-of-range duration, malformed input; `_pin_output_params` values and H-before-W ordering; `upsample()` invalid_size returns correct reason — required.
- **Contract:** existing `test_audio.py` contract tests must pass with updated `upsample()` mock signature.
- **Smoke:** none — engine call unchanged; full end-to-end smoke is Story 8.

## Estimated Complexity

M — replaces the upsample() core; multiple interlocking pieces but each is small.
