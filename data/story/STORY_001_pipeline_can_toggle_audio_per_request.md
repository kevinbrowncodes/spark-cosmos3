# STORY_001 — Pipeline can explicitly enable or disable audio per generation request

## User Story

As the pipeline, I want to tell the gateway whether I want audio on this generation so that the gateway applies the correct sound settings and audio prompt directive without me needing to know the internal field names.

## Context

The gateway already forwards `generate_sound` to vLLM-Omni, but the field name is an internal API gotcha (`generate_sound` / `sound_duration` — never `enable_audio`). The pipeline should send a single, clear boolean and trust the gateway to handle the rest. The audio house-style directive in `data/audio.txt` should only be appended to the prompt when audio is on.

Currently this behaviour exists but is undocumented and untested as a formal contract. This story formalises and tests it.

## Acceptance Criteria

- [x] `POST /generate` accepts `generate_sound` (boolean, default `true`)
- [x] When `generate_sound=true`: the `data/audio.txt` directive is appended to the prompt (unless the upsampler already included it), `generate_sound=true` and `sound_duration` are forwarded to vLLM-Omni
- [x] When `generate_sound=false`: the audio directive is **not** appended to the prompt, `generate_sound=false` is forwarded, `sound_duration` is still sent (vLLM-Omni requires it regardless)
- [x] `GET /audio` returns the current audio house style text and the default setting so the pipeline can inspect what will be applied
- [x] Response from `GET /audio` includes `{ "default_enabled": true, "directive": "<contents of data/audio.txt>" }`
- [x] All existing `/generate` calls that omit `generate_sound` continue to behave as before (audio on by default)

## Technical Notes

- `gateway/server.py` — `generate_sound: bool = Form(True)` is already on the `/generate` handler; audio.txt append logic is already in place. The main work is the new `GET /audio` endpoint and the contract test.
- `data/audio.txt` is read at request time via `_read_data("audio.txt")`, so changes to the file are live without a gateway restart.
- The upsampler path already receives `generate_sound` and `audio_style` — no change needed there.
- Do **not** add a persistent server-side audio toggle (state that survives requests). Per-request is the right scope; a server-side default would create hidden behaviour.

## Testing Plan

- **Unit**: pytest — `test_audio_directive_appended_when_sound_on`, `test_audio_directive_omitted_when_sound_off`, `test_generate_sound_false_still_sends_sound_duration`. Mock the httpx call to the engine.
- **Contract**: curl test against a running gateway — `GET /audio` returns 200 with `directive` and `default_enabled` fields. `POST /generate` with `generate_sound=false` returns a job (4-step smoke, tiny image) and the logged prompt does not contain the audio.txt text.
- **Smoke**: not required — this story does not change the generation path, only what's forwarded in the form.

## Estimated Complexity

Small — one new read-only endpoint, one pytest file, one curl test. The generate path is already correct; this story mainly adds the `GET /audio` inspection endpoint and formalises the test contract.
