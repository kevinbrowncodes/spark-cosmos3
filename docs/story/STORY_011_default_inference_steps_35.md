# STORY 011 — Restrict Inference Steps to 35 (Default) or 50 (High Quality)

As a gateway operator, I want `num_inference_steps` to accept only 35 or 50 — with 35 as the default — so clients choose a quality level without needing to know what a step count means, and bad values (e.g. a leaked smoke-test 4) are rejected outright.

## Acceptance Criteria

- [x] `num_inference_steps` default in `POST /generate` changed from 50 → 35.
- [x] Any value other than 35 or 50 → HTTP 400 with a clear error message.
- [x] The default and allowed values apply to all modes (video-only and audio-visual). Not conditional on `generate_sound`.
- [x] `docs/api.md` updated: "num_inference_steps: 35 (default, NVIDIA model-card reference) or 50 (high-quality override, paper eval config). Any other value returns 400."
- [x] `CLAUDE.md` smoke test convention updated: smoke tests now use `num_inference_steps=35` (the minimum allowed value).
- [x] `python -m pytest gateway/tests/` passes.
- [x] `curl -s localhost:8002/health` returns 200.

## Technical Notes

- The 50 in technical-report Table 21 is the audio-visual benchmark-eval default. NVIDIA's four runnable Nano model-card examples (I2V, T2V, and both with-sound variants) all use `num_inference_steps=35`. The I2V car example uses seed=1111 at 35 steps.
- Implementation in `server.py`: change the Form default to 35, then validate immediately after: `if num_inference_steps not in (35, 50): raise HTTPException(400, ...)`.
- Side effect: smoke tests can no longer use 4 steps. Update `CLAUDE.md` Section 9 to reflect 35 as the smoke/minimum value. 35 steps runs in ~5–6 min at 720p (vs ~40–50 min at 50 steps) — acceptable for a smoke check.
- `FIXED_PARAMS` in `server.py` does not include `num_inference_steps` — no change needed there.

## Testing Plan

- **Unit:** add a contract test asserting that `num_inference_steps=20` → 400 and that omitting the field results in `35` in the forwarded engine form.
- **Contract:** existing tests pass explicit values or mock the call — update any that pass `num_inference_steps=4`.
- **Smoke:** submit one job without `num_inference_steps` and confirm `engine_request.num_inference_steps == "35"` in the job log.

## Estimated Complexity

XS — two-line change in server.py, doc/CLAUDE.md updates, one new contract test.
