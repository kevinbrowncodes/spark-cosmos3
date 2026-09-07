# BUG_008 — The Flow sidecar runs as root, so the media folder fills with root-owned files

**Status:** Open
**Found:** 2026-09-07, STORY_032 (driving the Agent UI from a host-run sidecar against the shared media dir)
**Affects:** `flow` (`cosmos3-flow` writes `/media`); the gateway has the same habit with `data/logs/jobs/` (root-owned since 2026-06-26) — noted here, not fixed here

## Summary

`docker-compose.yml` starts `cosmos3-flow` without a `user:`, so uvicorn runs as
root and every directory and file it creates under the bind-mounted
`~/Documents/flow-media/` (`flow-uploads/`, `flow-outputs/`, `flow-outputs-raw/`,
`flow-runs/`) is `root:root 755`. Consequences on the host:

- Kevin cannot delete or move his own clips without `sudo` (which this box does not grant password-free).
- Any sidecar run outside Docker against the same media dir — the pattern STORY_032 uses to serve the unreleased UI bundle — cannot write: `POST /flow/agent/runs` → **500**, `PermissionError: [Errno 13] Permission denied: '.../flow-runs/run_28535d285be1.tmp'`.
- Backups/rsync as the user skip or mangle the files.

## Steps to reproduce

```bash
ls -la ~/Documents/flow-media/            # subdirs owned by root
touch ~/Documents/flow-media/flow-runs/x  # Permission denied
```

## Expected vs actual

- **Expected:** everything the sidecar writes into the user's media folder belongs to the user who mounted it.
- **Actual:** root-owned, mode 755.

## Root cause

No `user:` in the compose service; the image never adds one either. Docker runs
the entrypoint as uid 0 and bind mounts preserve the container's uid on the host.

## Fix

- `docker-compose.yml`: `user: "${FLOW_UID:-1000}:${FLOW_GID:-1000}"` on the flow service (the image needs nothing from `/root`; `/media` is the only writable path). `.env.example` documents the two variables.
- One-off repair of what root already wrote, without sudo, via Docker itself:
  `docker run --rm -v ~/Documents/flow-media:/m python:3.12-slim chown -R 1000:1000 /m`

## Acceptance criteria

- [x] `docker compose config` shows `user: 1000:1000` for `flow`; the redeployed container reports `id -u` = 1000
- [x] After the repair, `ls -la ~/Documents/flow-media` shows only `kevinbrown` ownership and a host-run sidecar can create a run in the shared `flow-runs/`
- [x] A new upload and a new cached clip created by the redeployed container are owned by `kevinbrown`
