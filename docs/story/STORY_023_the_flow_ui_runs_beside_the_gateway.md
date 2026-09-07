# STORY_023 — The Flow UI runs beside the gateway in its own container

**Epic:** EPIC_002 — A browser UI for generating and extending clips
**Depends on:** STORY_013 (git SHA labels — the new image follows the same convention)
**Unblocks:** STORY_024 (settings Cosmos will accept), STORY_025, STORY_026

As an operator, I want the Flow UI to start as a fourth container next to the
engine, gateway and progress sidecar, so that opening `http://<spark>:8003/ui/`
shows the editor talking to *this* box — without a single line of
`gateway/server.py` changing.

This is a deliberately thin slice: the container builds, boots, answers the
Flow protocol contract, and serves the UI. **No render is triggered.** The
Cosmos-specific corrections to the upstream example (the `frames` list, the
`count` options, the `duration_s` source) are STORY_024; the first real
generation is STORY_025.

## Acceptance Criteria

- [ ] `flow/Dockerfile` builds from `python:3.12-slim`, installs `ffmpeg`, and installs `flow-protocol[server]` from the flow git tag named by `ARG FLOW_VERSION` (default `v0.1.0`)
- [ ] The same `FLOW_VERSION` downloads `flow-ui-${FLOW_VERSION}.tar.gz` from the flow GitHub release and unpacks it into `/app/flow-ui` — the pip pin and the UI pin can never disagree
- [ ] The image carries the `git.sha` label exactly as the gateway and progress images do (STORY_013)
- [ ] `flow/gateway.py` is a copy of upstream `protocol/python/flow_protocol/examples/cosmos3.py` at `FLOW_VERSION`; the only edits are the three relative imports rewritten as `flow_protocol.*` absolute imports, and a header recording the source tag and the SHA-256 of the upstream file so drift is detectable
- [ ] `flow/app.py` builds the ASGI app from environment: `COSMOS_GATEWAY_URL` (default `http://gateway:8002`), `FLOW_MEDIA_DIR` (default `/media`), `RESOLUTION_DICT` (default `/data/resolution_ratio_dict.json`), `FLOW_UI_DIR` (default `/app/flow-ui`)
- [ ] `docker-compose.yml` gains a `flow` service: image `spark-cosmos3-flow:latest`, container `cosmos3-flow`, port `8003:8003`, `restart: unless-stopped`, `depends_on: gateway`, volumes `${FLOW_MEDIA_DIR:-${HOME}/Documents/flow-media}:/media` and `./data:/data:ro`, build args `FLOW_VERSION` and `GIT_SHA`
- [ ] `.env.example` documents `FLOW_VERSION` and `FLOW_MEDIA_DIR`; the stale `AEON_URL` block (removed by STORY_022, and it names port 8003) is deleted
- [ ] `scripts/deploy.sh` builds `flow` with the SHA baked in and prints its label alongside the other two
- [ ] `flow-conformance http://localhost:8003` (contract only, run inside the container) passes every check
- [ ] `http://localhost:8003/ui/` loads the editor, the composer chip reads **Cosmos 3 Nano**, and no protocol-mismatch screen appears
- [ ] `curl localhost:8003/flow/capabilities` returns 200 with `"protocol": 1` — this is the sidecar's health check
- [ ] README gains a **Flow UI** section (port, `FLOW_VERSION`, the three-step upgrade: bump the pin → rebuild the image → re-run conformance) and `flow/` appears in the repo layout
- [ ] `flow/` holds ≥ 95 % line coverage; `requirements-dev.txt` and `pytest.ini` make `python3 -m pytest --cov=flow --cov-fail-under=95` runnable from a fresh checkout
- [ ] `git diff STORY_022..HEAD -- gateway/server.py` is empty

## Technical Notes

**Everything below was verified against flow `v0.1.0` on 2026-09-06.**

- The flow repo's default branch is `develop`; `main` does not exist. Pin the
  **tag**, never a branch: `git+https://github.com/kevinbrowncodes/flow@${FLOW_VERSION}#subdirectory=protocol/python`.
- The UI tarball is **flat** (`tar -czf … -C dist .` in `release.yml`; 26
  entries with `./index.html` at the root), so:
  `curl -fsSL …/flow-ui-${FLOW_VERSION}.tar.gz | tar -xz -C /app/flow-ui` — no
  `--strip-components`. The bundle uses a hash router and relative asset paths;
  `mount_ui(app, "/app/flow-ui")` at `/ui` is all it needs.
- `examples/cosmos3.py` imports `..gateway`, `..media`, `..models` relatively.
  Copied out of the package those fail at import time; they become
  `from flow_protocol.gateway import FlowGateway, UpstreamError` etc. Nothing
  else in the file changes in this story — the known-wrong options (`frames`
  300, `count` `[1, 2]`, `duration_s` from `seconds`) are **STORY_024's job**,
  and they are harmless here because nothing generates.
- `create_app(gateway, ui_dir=…)` already exists in `flow_protocol.router`; the
  entrypoint is `uvicorn flow.app:app --host 0.0.0.0 --port 8003`. One worker:
  `Cosmos3Gateway` keeps a per-job size hint in memory and a shared
  `httpx.Client`.
- The gateway is reached by its **compose service name** `gateway`
  (container `cosmos3-gateway`), not `localhost`. Media roots
  `/media/flow-uploads` and `/media/flow-outputs` are created by `MediaStore`
  on first start; the host dir `~/Documents/flow-media` is created by Docker.
- `flow-conformance` is a console script inside the image, so the check runs as
  `docker compose exec flow flow-conformance http://localhost:8003`. Do not
  pass `--generate` in this story.
- `ffmpeg` on `python:3.12-slim` arm64 is `apt-get install -y --no-install-recommends ffmpeg`
  (~90 MB). `uvicorn[standard]` pulls `uvloop`/`httptools`/`watchfiles`, all of
  which ship aarch64 cp312 wheels — no compiler in the image.
- Port 8003 is free on this box (checked with `ss -ltn`; 8000–8002 and 8004
  are the only listeners in that range). It was AEON's port; the `.env.example`
  block still advertising it goes.
- Build-time tests: a multi-stage Dockerfile whose `test` stage installs
  `requirements-dev.txt` and runs `pytest --cov=flow --cov-fail-under=95`; the
  final stage copies nothing from it — a red suite simply fails the build.
- The host Python is PEP 668-locked (`pip install --user` refuses). The
  documented local recipe is `python3 -m venv --system-site-packages .venv &&
  .venv/bin/pip install -r requirements-dev.txt` (`.venv/` is already gitignored).
- Memory: the sidecar is a ~60 MB Python process. No `free -h` gate, and it may
  be rebuilt or restarted during a render — it holds no GPU state.

## Testing Plan

- **Unit** (`flow/tests/test_gateway_unit.py`, `test_app_unit.py`): `sizes_from_resolution_dict` against the real `data/resolution_ratio_dict.json` and against a missing/empty tier; `_parse_size` for `704x1280`, `None`, junk; `STATUS` mapping including unknown → `failed`; `_to_job` for each status, dict-vs-string `error`, missing `seconds`; `app.py` environment parsing with and without every variable.
- **Integration** (`flow/tests/test_routes.py`): `TestClient(create_app(Cosmos3Gateway(...)))` with `:8002` faked by `respx` — `/flow/capabilities`; upload → list → FULL → THUMBNAIL (PNG upload, and an MP4 fixture to exercise the ffmpeg poster path); `/flow/generate` happy path, gateway 4xx → 422, gateway 5xx → 502, connection error → 502, unknown reference → 404; `/flow/jobs/{id}` 200 / 404 / 5xx; output fetch on first `/flow/media/out:…` access — success, upstream 404, mid-stream failure leaving no `.part` file; `flow_protocol.conformance.run_checks` executed in-process and asserted all-green.
- **Contract** (`flow/tests/contract.sh`, against the running container): `GET :8003/flow/capabilities` → 200, `protocol == 1`, `name == "Cosmos 3 Nano"`; `GET :8003/ui/` → 200 `text/html`; `GET :8003/flow/jobs/nope` → 404 JSON `detail`; `docker inspect spark-cosmos3-flow:latest` shows a `git.sha` label equal to `git rev-parse --short HEAD`.
- **E2E**: `docker compose exec flow flow-conformance http://localhost:8003` passes; open `http://localhost:8003/ui/` and confirm the editor renders with the Cosmos 3 Nano chip. **No render in this story** — the generation path is not exercised until STORY_025, and a real render here would burn ~44 min proving nothing this story changes.
- **Coverage**: `python3 -m pytest --cov=flow --cov-fail-under=95` green locally and in the Docker `test` stage.

## Estimated Complexity

**Medium.** No algorithmic work; the cost is in the Dockerfile (two pinned
downloads, multi-stage tests, arm64), the compose/deploy plumbing, and a test
suite that covers a file we did not write to 95 %.
