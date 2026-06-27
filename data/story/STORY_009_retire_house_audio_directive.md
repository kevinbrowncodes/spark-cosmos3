# STORY 009 — Retire the House Audio Directive; Let Opus Own Audio

As a gateway operator, I want to remove the `data/audio.txt` house style directive and stop appending it to prompts, so that the upsampler (Opus) writes scene-contextual `audio_description` values freely without a blanket ambient-only constraint.

## Acceptance Criteria

- [x] `data/audio.txt` deleted from the repo.
- [x] `server.py`: `audio_style` local variable and the block that appends it to the prose fallback prompt removed. The prose fallback sends the prompt as-is (no audio annotation).
- [x] `server.py`: `GET /audio` endpoint removed (no callers in the pipeline; the directive it served no longer exists).
- [x] `generate_sound=False` still correctly blanks `audio_description` in the upsampled JSON (existing behaviour in `upsampler.py` — no change needed).
- [x] `generate_sound` and `sound_duration` multipart fields still sent to vLLM-Omni unchanged.
- [x] `sync_config.sh` no longer syncs `audio.txt` (it was synced by the flat-file glob — removal from `data/` is sufficient; verify with `--check`).
- [x] `python -m pytest gateway/tests/` passes.
- [x] `curl -s localhost:8002/health` returns 200.

## Technical Notes

- The upsampler schema has an `audio_description` field; Opus fills it contextually. When `generate_sound=True`, this is the only audio guidance now. When `generate_sound=False`, `upsampler.py` already blanks it — that path is unchanged.
- The prose fallback (no API key, upsampler failure) will send the prompt with no audio annotation. This is acceptable: fallback quality is secondary, and adding no directive is better than a stale one.
- `GET /audio` has no callers in the pipeline (`cosmos_client.py` does not call it). Safe to remove.
- CLAUDE.md references `data/audio.txt` in the architecture section — update that reference as part of this story.

## Testing Plan

- **Unit:** existing `test_audio.py` contract tests mock `upsampler.upsample` — check whether any assert on the audio directive being present in the prose path and update if so. No new tests needed.
- **Contract:** none beyond the existing suite.
- **Smoke:** none — audio generation path in vLLM-Omni is unchanged; only the prompt annotation changes.

## Estimated Complexity

XS — delete a file, remove ~5 lines from server.py, one endpoint removal, update CLAUDE.md.
