# STORY 005 — Replicate NVIDIA's Prompt-Build Logic in the Gateway

As a gateway operator, I want the upsampler to assemble the prompt using NVIDIA's official template-fill logic, so that the structured JSON caption sent to the model is byte-identical to what the framework would produce.

## Acceptance Criteria

- [x] `build_nl_description` and `build_upsampler_prompt` added to `gateway/upsampler.py`, transcribed from `cosmos_framework.inference.prompt_upsampling` (lines 121–193).
- [x] Module-level constants `TEMPLATE`, `SCHEMA`, `RRD`, `I2V_INTRO`, `I2V_IMAGE_NOTE` loaded via `Path(__file__)` so the gateway starts correctly from any working directory.
- [x] Golden fixtures generated from the framework's logic against the vendored files and committed as `gateway/tests/fixtures/upsampler_prompt_720_169.txt` and `gateway/tests/fixtures/upsampler_prompt_720_916.txt`.
- [x] Pytest test in `gateway/tests/test_upsampler_prompt.py` asserts `build_upsampler_prompt` output is byte-for-byte identical to both fixture files.
- [x] Existing `upsample()` function and fallback paths are unchanged — wiring comes in Story 7.
- [x] `python -m pytest gateway/tests/` passes.

## Technical Notes

- `build_upsampler_prompt` receives `resolution`, `aspect_ratio`, and `duration` as pre-computed strings from `_parse_size` (Story 7). Do not re-derive duration here.
- The `resolution_ratio_dict` embedded in the prompt uses H-first key order `{"H":…, "W":…}` — matches `_resolution_ratio_dict_text()` in the framework.
- `string.Template` is safe: the schema is a substitution value and is never re-scanned.
- The existing `build_user_text` / `_OUTPUT_TEMPLATE` / `_duration_mss` / `_aspect` functions stay in place until Story 7 replaces the `upsample()` call.

## Testing Plan

- **Unit:** pytest golden test (landscape + vertical) — required.
- **Contract:** none — no endpoint changes.
- **Smoke:** none — `upsample()` is unchanged, generation path unaffected.

## Estimated Complexity

S — add ~40 lines of code + fixtures + one test file.
