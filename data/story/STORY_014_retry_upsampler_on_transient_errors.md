# STORY_014 — Retry the prompt upsampler automatically when Anthropic is temporarily unavailable

As a pipeline operator, I want the gateway to retry the Opus prompt-upsampling call on transient errors before falling back to prose, so that a momentary Anthropic 529 overload does not silently degrade generation quality.

## Acceptance Criteria

- [x] The upsampler makes up to **3 attempts total** before giving up, with a **fixed 30-second wait** between attempts
- [x] The following errors trigger a retry: HTTP 529 (`overloaded_error`), HTTP 429 (rate limit), HTTP 500 / 502 / 503, and connection/read timeouts
- [x] The following errors do **not** trigger a retry: HTTP 413 (`request_too_large`), HTTP 400, and any other 4xx — retrying cannot help
- [x] After all 3 attempts fail, the existing fallback behaviour is preserved: `prompt_source` is set to `"prose"` and `upsample_fallback_reason` records the final error
- [x] When a retry is needed, the attempt number and error are logged at WARNING level before the wait
- [x] The provenance block includes `upsample_attempts: N` (1 = succeeded first try, 2 or 3 = retried) so retry frequency is visible without digging through logs
- [x] The retry sleep uses `asyncio.sleep` (not `time.sleep`) so the 30-second wait does not block the FastAPI event loop and freeze other in-flight requests

## Technical Notes

- All retry logic lives in `gateway/upsampler.py`. No changes to `server.py` beyond receiving the updated provenance field.
- Use `asyncio.sleep(30)` between attempts. The upsampler must be called with `await` from the endpoint, which it already is.
- Catch `anthropic.APIStatusError` for HTTP error codes; check `e.status_code`. Catch `anthropic.APIConnectionError` and `httpx.ReadTimeout` for network-level failures.
- Retryable status codes: `{429, 500, 502, 503, 529}`. Non-retryable: anything else (treat all other 4xx as deterministic failures).
- The `upsample_attempts` field should be added to the provenance dict returned by the upsampler alongside the existing `prompt_source` and `upsample_fallback_reason` fields.

### Client timeout budget (important)

The ogtv-studios pipeline client has a **150s submit timeout** on `POST /generate`. Upsampling runs synchronously before the job ID is returned. Worst-case with this design:

- 3 failing attempts at ~2s each (529 returns fast) = ~6s
- 2 waits × 30s = 60s
- Total worst case (all 3 fail): ~66s → well within 150s

If retries are ever increased beyond 3, or changed to exponential backoff, **raise the client timeout first**.

## Testing Plan

- **Unit** — mock the Anthropic client to:
  - Return 529 twice then succeed on attempt 3; assert `upsample_attempts: 3` and the structured prompt is returned
  - Return 529 three times; assert fallback to prose with `upsample_attempts: 3` and `upsample_fallback_reason` set
  - Return 400 on attempt 1; assert no retry and immediate prose fallback
  - Return 413 on attempt 1; assert no retry and immediate prose fallback
  - Raise `APIConnectionError`; assert retry is triggered
- **Contract** — not applicable; no change to the `/generate` request or response shape visible to clients (provenance is in job logs, not the HTTP response)
- **Smoke** — not applicable; retry path only activates on Anthropic errors, which cannot be reliably induced against the live API

## Estimated Complexity

Small — contained to `gateway/upsampler.py` with unit test coverage. No schema, endpoint, or docker-compose changes.
