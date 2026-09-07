# STORY_016 — Show the pipeline the rewritten prompt the gateway actually sent

As a pipeline operator, I want the gateway to return the upsampled prompt it built for each generation — in both the submit response and the job-status response — so the pipeline can capture, persist, and later display exactly what was sent to Cosmos for each clip.

## Acceptance Criteria

- [x] `POST /generate` includes an `upsampler_output` field in its JSON response
- [x] `upsampler_output` holds the exact structured prompt string sent to the engine when `prompt_source == "upsampled"`, and is `null` otherwise (mirrors the value already passed to `job_logger.write(upsampler_output=…)`)
- [x] `GET /jobs/{id}` echoes the same `upsampler_output` field for the life of the job's in-memory record
- [x] The field is additive — existing clients that ignore it are unaffected; no existing field is renamed or removed
- [x] The prose fallback path (`prompt_source == "prose"`) returns `upsampler_output: null`, not the prose text — the field means "what the upsampler produced," consistent with the job log

## Technical Notes

- The value already exists: [`gateway/server.py`](../../gateway/server.py) computes `full_prompt` and, when `prompt_source == "upsampled"`, passes it as `upsampler_output` to `job_logger.write(...)`. This story only surfaces that same value on the API.
- **`/generate` response:** after `job["prompt_source"]` / `job["upsample_fallback_reason"]` are set, add
  `job["upsampler_output"] = full_prompt if prompt_source == "upsampled" else None`.
- **`/jobs/{id}` echo:** store the prompt in `_JOB_META[video_id]` (e.g. key `upsampler_output`) at submit time, and expose it in `job_status` alongside the existing `prompt_source` / `upsample_fallback_reason` / `reasoner` echo. `_JOB_META` is already bounded by `_JOB_META_MAX`, so the added few-KB string per job is safe.
- Keep the field name **`upsampler_output`** — identical to the job-log key — so the vocabulary is consistent across the log file, the submit response, and the status response.
- No changes to the engine form, `extra_params`, schema, or docker-compose. No new dependencies.
- Update `docs/api.md` (and `docs/responses.md` if it captures a `/generate` sample) to document the new response field.

## Testing Plan

- **Unit** — with the upsampler mocked:
  - `upsample=true` and a successful upsample → `/generate` response contains `upsampler_output` equal to the structured prompt string
  - `upsample=false` → `upsampler_output` is `null`
  - Upsample fails and falls back to prose → `upsampler_output` is `null` (not the prose text)
  - `_JOB_META` for the returned job id carries the same `upsampler_output`, and `GET /jobs/{id}` echoes it
- **Contract** — curl/httpx against a running gateway:
  - `POST /generate` with `upsample=true` returns a body containing a non-null `upsampler_output`
  - `GET /jobs/{id}` for that job returns the same `upsampler_output` value
  - Omitting/using the prose path returns `upsampler_output: null` and still returns a valid job id (backward-compat)
- **Smoke** — not required; the generation path (engine form, params, weights) is unchanged. Only response serialization and in-memory meta change.

## Estimated Complexity

Small — surfacing a value that already exists. Two response sites, one `_JOB_META` field, unit + contract coverage, docs touch-up. No engine, schema, or compose changes.
