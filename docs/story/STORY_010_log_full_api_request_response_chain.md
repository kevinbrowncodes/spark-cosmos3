# STORY 010 — Log the Full API Request/Response Chain

As a gateway operator, I want every job log to include the full Anthropic API request and response (prompt sent, raw reply, token usage, latency) and the full vLLM-Omni form fields sent to the engine, so I can inspect and debug the entire chain for any generation offline.

## Acceptance Criteria

- [x] `upsample()` returns a third value: a metadata dict (or `None` if the Anthropic API call was never made). Dict contains: `model`, `prompt_sent` (full upsampler prompt text), `sampling_params`, `raw_response` (Opus's full text before JSON extraction), `stop_reason`, `usage` (`input_tokens`, `output_tokens`), `latency_s`.
- [x] `job_logger.write()` accepts `upsampler_meta: dict | None` and `engine_form: dict | None`; writes them into the JSON log under `upsampler.api` and `engine_request`.
- [x] `server.py` captures the `form` dict before the engine POST and passes both `upsampler_meta` and `engine_form` to `job_logger.write()`.
- [x] On a successful upsampler call, a `print()` to stdout logs latency and token counts (visible in `docker logs cosmos3-gateway`).
- [x] All existing fallback paths still return `(None, reason, None)` — meta is `None` whenever the Anthropic call was not made (no API key, invalid size) or not reached (exception before the call).
- [x] `python -m pytest gateway/tests/` passes.

## Technical Notes

- `upsample()` signature: `-> tuple[str | None, str | None, dict | None]`. All callers (only `server.py`) must be updated to unpack three values.
- `prompt_sent` is the output of `build_upsampler_prompt(...)` — the full text, not a summary. It is long (~8 KB) but is the ground truth of what was sent to Opus.
- `latency_s` is measured from just before `client.messages.create()` to just after it returns, using `time.monotonic()`.
- The `engine_form` dict passed to `job_logger` should be the same `form` dict built in `server.py` (all string values), minus `extra_params` expansion — log it as-is. The image bytes are in `files`, not `form`, so they are never logged.
- `job_logger` record layout after this story:
  ```json
  {
    "upsampler": {
      "output": { ... },
      "fallback_reason": null,
      "api": {
        "model": "claude-opus-4-8",
        "prompt_sent": "...",
        "sampling_params": { "temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 8192 },
        "raw_response": "```json\n{ ... }\n```",
        "stop_reason": "end_turn",
        "usage": { "input_tokens": 3241, "output_tokens": 812 },
        "latency_s": 14.3
      }
    },
    "engine_request": {
      "prompt": "...",
      "negative_prompt": "...",
      "size": "720x1280",
      "num_frames": "189",
      ...
    }
  }
  ```

## Testing Plan

- **Unit:** update `test_upsampler_size.py::TestUpsampleInvalidSize` to unpack three values from `upsample()`; confirm `meta` is `None` for the invalid-size path. Update any other test that calls `upsample()` directly.
- **Contract:** `test_audio.py` mocks `upsampler.upsample` returning `(None, "disabled_by_request")` — update mock return to `(None, "disabled_by_request", None)`.
- **Smoke:** none — generation path unchanged.

## Estimated Complexity

S — additive change; no control flow changes, only new data captured and threaded through.
