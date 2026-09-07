# BUG_004 — The engine container has emitted no Docker logs since 2026-06-20

**Status:** Root cause found 2026-09-07; workaround in use, permanent fix waits for a container recreate
**Found:** 2026-09-06, while verifying STORY_023 (Flow sidecar)
**Affects:** progress sidecar (`:8001`, terminal-signal pin), the CLAUDE.md §4 guard `docker logs cosmos3-api --since 10m`, any log-based debugging

## Summary

`cosmos3-api` answers `/health` 200 and its `vllm serve` process (PID 1) has
been up since **2026-08-20 14:13** (`docker inspect` `StartedAt`; `ps` elapsed
≈ 17.5 days), yet `docker logs cosmos3-api` contains **nothing newer than
2026-06-20T15:57**. `--since 24h`, `--since 720h` and `--since 2026-06-20T16:00`
all return 0 lines. The last lines present are a clean shutdown sequence
(`Worker 0: Shutdown complete`, `Stage 0 replica 0 shut down`).

## Steps to reproduce

```bash
docker inspect cosmos3-api --format '{{.State.StartedAt}}'        # 2026-08-20T14:13:09Z
docker logs cosmos3-api --timestamps 2>&1 | tail -1               # 2026-06-20T15:57:09Z …
docker logs cosmos3-api --since 720h 2>&1 | wc -l                 # 0
curl -s localhost:8000/health -o /dev/null -w '%{http_code}\n'    # 200
curl -s localhost:8001/progress                                   # age_s ≈ 1512890 = the process uptime
```

## Root cause, found 2026-09-07

**The container never stopped logging. `docker logs` stops *reading*.** Measured while the
engine was actively loading and answering requests:

| command | lines | newest timestamp |
|---|---|---|
| `docker logs cosmos3-api` | 48,792 | 2026-06-20T15:57:09 |
| `docker logs cosmos3-api --tail 60000` | 60,000 | 2026-09-07T22:58:41 |
| `docker logs cosmos3-api --tail 5` | 5 | 2026-09-07T22:58:41 |
| `docker logs cosmos3-api --since 5m` | 0 | — |

One `json-file` log, no rotation configured, **60 MB** on disk and its mtime is current. A
sequential read gives up part-way through and returns everything before the break, which is
why every full read ends on 2026-06-20 and why `--since` — which uses that same sequential
path — returns nothing at all. Reading backwards from the end (`--tail N`) sails past the
break and shows the live output. Nothing was lost; it is unreachable from the front.

So the log has been readable this whole time, with `--tail`, and the sidecar and the
CLAUDE.md guard were both using the one access path that cannot work.

## What to do about it

- **Now:** read the engine with `docker logs cosmos3-api --tail 200`. Never `--since`.
- **Permanently:** the container needs a fresh log file, which means a recreate
  (`docker compose up -d --force-recreate cosmos3`), not a restart — a restart keeps the
  same file. `docker-compose.yml` now sets `max-size: 50m` / `max-file: 3` on the engine so
  an unrotated 60 MB file cannot build up again. Do it when nothing is rendering; it costs
  the usual ~3.5 min reload.
- The progress sidecar (`:8001`) should be re-checked afterwards — its terminal-signal pin
  has been reading a log it could not see past.

## Expected vs actual

- **Expected:** a container started on 08-20 logs several minutes of model
  loading, then one access-log line per API call; the sidecar's `/progress`
  reflects the newest tqdm bar.
- **Actual:** zero lines captured since the restart; the sidecar's "last seen"
  is pinned at the moment the container started; the CLAUDE.md render guard
  (`docker logs --since 10m`) is always quiet, whether or not a render runs.

## Root cause

**Unknown.** Verified so far: log driver is `json-file` with no rotation
config; PID 1's fds 1 and 2 are pipes created at 08-20 14:13 (so stdout/stderr
are wired to Docker); the Docker data disk is not full (a 700 MB image built
today). Suspects, unverified: the json log file handle inside `dockerd` was
lost across a daemon restart/upgrade between 06-20 and 08-20 (the container was
`docker start`ed, not recreated — `Created` is still 2026-06-12); or vLLM's
logging was redirected inside the container. Needs `/var/lib/docker/containers/<id>/*-json.log`
mtime/size (root) and a look at `journalctl -u docker` around 08-20.

## Acceptance criteria

- [ ] Root cause identified and written here
- [ ] `docker logs cosmos3-api --since 10m` shows live access-log lines during a request
- [ ] `GET :8001/progress` `age_s` drops to seconds after a render's denoise loop completes
- [ ] If the fix is "recreate the container", `docs/spark-notes.md` says so and when it is safe (no render in flight — the sidecar is blind, so check `GET :8002/jobs/{id}` for the last submitted job instead)

## Workaround while open

The gateway's moving progress bar is an elapsed-time estimate and does not
depend on these logs, so renders (and the Flow UI) still work; only the
sidecar's end-of-denoise "→ 99" pin is lost. Before restarting anything,
check for an in-flight job via the gateway's job log directory (`data/logs/jobs`,
newest entry) and `GET :8002/jobs/{id}` rather than `docker logs`.
