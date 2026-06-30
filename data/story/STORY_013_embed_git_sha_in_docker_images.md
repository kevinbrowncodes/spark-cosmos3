# STORY_013 — Show which code version is running inside each Docker image

As an operator running the same stack on two Sparks, I want to be able to confirm at a glance that both machines are running the same gateway and sidecar code, so I can rule out version drift when debugging generation differences.

## Acceptance Criteria

- [ ] `docker inspect spark-cosmos3-gateway:latest` includes a `git.sha` label showing the short commit hash the image was built from
- [ ] `docker inspect spark-cosmos3-progress:latest` includes the same `git.sha` label
- [ ] A `scripts/deploy.sh` script builds and starts the stack with the git SHA baked in automatically — no manual flag required
- [ ] Running `scripts/deploy.sh` on both Sparks and comparing `git.sha` labels confirms whether they are on the same code
- [ ] The engine image (`vllm/vllm-omni:cosmos3`) is unaffected — it is already pinned by digest in docker-compose.yml

## Technical Notes

- Add `ARG GIT_SHA=unknown` + `LABEL git.sha=$GIT_SHA` to `gateway/Dockerfile` and `progress-sidecar/Dockerfile`
- Add a `build.args` block to each service in `docker-compose.yml` passing `GIT_SHA: ${GIT_SHA:-unknown}`
- `scripts/deploy.sh` sets `GIT_SHA=$(git rev-parse --short HEAD)` and exports it before calling `docker compose up -d --build`
- `latest` tag stays as-is — docker-compose.yml does not need per-commit tag changes
- Verify with: `docker inspect spark-cosmos3-gateway:latest | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['Config']['Labels'])"`

## Testing Plan

- **Unit**: not applicable — no gateway logic changes
- **Contract**: not applicable — no API changes
- **Smoke**: after running `scripts/deploy.sh`, confirm `docker inspect` on both images shows a non-empty `git.sha` label matching `git rev-parse --short HEAD`
