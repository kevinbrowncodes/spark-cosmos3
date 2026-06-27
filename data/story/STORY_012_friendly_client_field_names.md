# STORY 012 — Friendly Client Field Names; Gateway Owns All Translation

As a gateway operator, I want the client→gateway contract to use friendly, intent-driven names so that clients speak only creative intent and never see vLLM-Omni's wire format.

## Acceptance Criteria

- [x] `POST /generate` accepts the following friendly field names (old names removed):

  | Friendly (client) | Was | Notes |
  |---|---|---|
  | `image` | `input_reference` | file part; conditioning frame |
  | `prompt` | `prompt` | unchanged |
  | `size` | `size` | unchanged |
  | `frames` | `num_frames` | default 189, clamped 5–300 |
  | `steps` | `num_inference_steps` | 35 or 50 only; default 35 |
  | `sound` | `generate_sound` | bool; default true |
  | `upsample` | `upsample` | unchanged |
  | `seed` | `seed` | optional; unchanged |

- [x] Gateway translates friendly names to vLLM-Omni wire names before forwarding.
- [x] Gateway continues to inject all fields the client never sends: `negative_prompt`, `guidance_scale`, `flow_shift`, `max_sequence_length`, `extra_params`, `fps`, `sound_duration`.
- [x] Old field names (`input_reference`, `num_frames`, `num_inference_steps`, `generate_sound`) no longer accepted — sending them is silently ignored by FastAPI (field not found → default used).
- [x] `docs/api.md` updated to publish the friendly contract and the gateway's translation/injection table.
- [x] All gateway tests updated to use friendly field names.
- [x] `python -m pytest gateway/tests/` passes.
- [x] `curl -s localhost:8002/health` returns 200.

## Pipeline Coordination Required

**This is a breaking change for the pipeline client.** Must be deployed to the gateway and the pipeline simultaneously (or pipeline updated first with old names still working — but old names are NOT kept). Coordinate with the pipeline before merging.

Pipeline changes needed (tell the pipeline Claude):
- `input_reference` file field → `image`
- `num_frames` → `frames`
- `generate_sound` → `sound`
- `num_inference_steps` → already removed per Story 11; confirm it's gone

## Technical Notes

- FastAPI form field rename: change parameter names in the `generate()` signature. The file upload changes from `UploadFile = File(...)` parameter named `input_reference` to one named `image`.
- `sound_duration` is derived server-side (`frames / fps`) — client never sends it. No change needed there.
- `upsample` and `seed` are already friendly names — no change needed.
- `job_logger.write()` currently logs `image_filename` and `image_media_type` — these come from the upload field and don't need renaming (they're internal log fields, not client fields).
- No vLLM-Omni field names should appear in `docs/api.md`'s client-facing section after this story.

## Testing Plan

- **Unit:** update all existing tests that post `input_reference`, `num_frames`, `generate_sound`, or `num_inference_steps` to use the new names.
- **Contract:** verify that the engine receives `num_frames`, `generate_sound`, `num_inference_steps` (vLLM-Omni wire names) in the forwarded form, even though the client sent `frames`, `sound`, `steps`.
- **Smoke:** none — engine path unchanged.

## Estimated Complexity

S — rename form parameters in server.py + update tests + docs. No logic changes.
