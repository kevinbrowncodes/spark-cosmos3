# STORY_002 — Gateway saves a log file for every generation showing the full prompt chain

## User Story

As the developer, I want every generation to leave behind a log file showing the original prose prompt, what the upsampler produced, and the Cosmos API response, so that I can inspect, debug, and improve prompt quality over time.

## Context

`gateway/job_logger.py` already exists and writes one JSON file per job to `/logs/jobs/` inside the container. However:

1. `job_logger.py` is not listed in the `gateway/Dockerfile` `COPY` instruction, so it is never included in the built image — the module is missing at runtime and no logs are written.
2. The host volume mount points to `./logs/` at the repo root, outside of the `data/` directory. Log files should live under `data/logs/jobs/` so that all runtime artifacts produced by this repo are co-located under `data/`.
3. `data/logs/` must be gitignored so log files are never committed.

## Acceptance Criteria

- [ ] `gateway/Dockerfile` `COPY` line includes `job_logger.py`
- [ ] `docker-compose.yml` volume mount for job logs points to `./data/logs:/logs`
- [ ] `data/logs/` is covered by `.gitignore` (the directory itself is tracked, log files are not)
- [ ] After a completed generation, a file matching `data/logs/jobs/{timestamp}_{job_id}.json` exists on the host
- [ ] Each log file contains: `request.prompt` (original prose), `upsampler.output` (structured JSON or null), `upsampler.fallback_reason` (null or reason string), and `cosmos` (Cosmos API response)
- [ ] If the upsampler was skipped or failed, `upsampler.output` is `null` and `upsampler.fallback_reason` is populated
- [ ] A failure to write the log file does not crash the gateway or fail the generation request

## Technical Notes

- `gateway/Dockerfile`: change `COPY server.py upsampler.py ./` → `COPY server.py upsampler.py job_logger.py ./`
- `docker-compose.yml`: change `./logs:/logs` → `./data/logs:/logs` on the gateway service
- `.gitignore`: add `data/logs/` (or `data/logs/**` to track the directory but not its contents)
- `job_logger._LOG_DIR` defaults to `/logs/jobs` via `LOG_DIR` env var — no code change needed, the volume remapping handles it
- After changes: `docker compose build cosmos3-gateway && docker compose up -d --no-deps cosmos3-gateway`
- The old `./logs/` directory at the repo root can be deleted once the new mount is confirmed working

## Testing Plan

- **Unit**: not required — `job_logger.py` has no logic beyond JSON serialisation and file I/O; the contract test is sufficient.
- **Contract**: after rebuilding and restarting the gateway, submit a 4-step smoke generation (`num_inference_steps=4`). Once the job completes, verify `data/logs/jobs/` contains a `.json` file for that `job_id`, and that it has non-empty `request.prompt`, a `cosmos` key, and either a populated `upsampler.output` or a non-null `upsampler.fallback_reason`.
- **Smoke**: not required — this story does not change the generation path.

## Estimated Complexity

Small — two-line config change (Dockerfile + docker-compose.yml), one gitignore entry, one contract test. No logic changes.
