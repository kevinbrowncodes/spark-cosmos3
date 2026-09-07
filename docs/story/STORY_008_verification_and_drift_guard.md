# STORY 008 — Verification and Drift Guard for Vendored Upsampler Files

As a gateway operator, I want a checksum script and golden prompt tests to detect upstream drift in the vendored NVIDIA upsampler files, and a docs update confirming what we vendored, so that any future re-vendor is immediately flagged.

## Acceptance Criteria

- [x] **Golden prompt test** exists in `gateway/tests/test_upsampler_prompt.py`: assembles the prompt and diffs byte-for-byte against `gateway/tests/fixtures/upsampler_prompt_720_169.txt` and `gateway/tests/fixtures/upsampler_prompt_720_916.txt` — both generated from the `cosmos-framework` clone, not a convenience copy.
- [x] **Checksum check script** (`scripts/check_upsampler_sources.sh`) re-fetches the upstream template and schema raw files, compares sha256 against `data/SOURCES.md`, and exits non-zero with a diff summary if upstream changed.
- [x] **End-to-end smoke**: one I2V job at `num_inference_steps=4` confirms the pinned JSON is accepted by vLLM-Omni and returns an MP4.
- [x] `docs/cosmos-framework.md` updated: adds a vendored components section noting "vendored: template, schema, resolution_ratio_dict, pinning logic (see `data/SOURCES.md`)".

## Technical Notes

- The golden tests already exist from Story 5 (`test_upsampler_prompt.py`); this story's AC is satisfied once Story 5 tests pass.
- The checksum script checks only `upsampler_template.txt` and `upsampler_schema.json` against their raw URLs. The resolution_ratio_dict is extracted from a Python source file — the script checks the sha256 of the source file (`prompt_upsampling.py`).
- Smoke test uses `num_inference_steps=4` to complete quickly (~3–5 min instead of ~50 min).
- The `docs/cosmos-framework.md` update adds a "Vendored components" section rather than modifying the existing survey text.

## Testing Plan

- **Unit:** golden prompt tests (already in `test_upsampler_prompt.py`) — required, verify pass.
- **Contract:** none — checksum script is a shell utility, not a gateway endpoint.
- **Smoke:** one I2V generation at `num_inference_steps=4` — required (this story exists to verify end-to-end acceptance by vLLM-Omni).

## Estimated Complexity

S — shell script + doc update + smoke run. Tests already exist.
