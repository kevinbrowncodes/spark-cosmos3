# BUG_006 — Ollama binds loopback, so no container can reach Gemma

**Status:** Open — needs a one-line host change with sudo
**Found:** 2026-09-07, STORY_029 E2E (the agent's planner could not connect); the gateway has the same problem
**Affects:** `gateway` (`reasoner=gemma` upsampling — the default since STORY_022), `flow` (the agent's planner, EPIC_003)

## Summary

`ollama serve` listens on `127.0.0.1:11434` (`ss -ltn`). Docker containers reach
the host via `host.docker.internal` → the bridge gateway IP (172.x), which a
loopback-only socket refuses. So from inside **any** container:

```
httpx.get("http://host.docker.internal:11434/api/version") → ConnectError: [Errno 111] Connection refused
```

Verified from both `cosmos3-gateway` and `cosmos3-flow`. STORY_022 predicted this
(*"Ollama binds 127.0.0.1:11434 and OLLAMA_HOST is unset, so the gateway
container cannot reach it"*) and left its acceptance box **"The gateway reaches
Ollama from inside its container"** unchecked. It was never closed.

## Steps to reproduce

```bash
ss -ltn | grep 11434                                    # 127.0.0.1:11434
docker compose exec gateway python -c "import httpx; httpx.get('http://host.docker.internal:11434/api/version', timeout=5)"
# → ConnectError: Connection refused
```

## Expected vs actual

- **Expected:** `upsample=true` (the default) rewrites the prompt with Gemma; the agent's `POST /agent/plan` returns scripts.
- **Actual:** the gateway's Gemma call fails on connect and falls back to prose (`upsample_fallback_reason: api_error: …`); the planner returns 502 `ollama unreachable`. No render has been submitted since STORY_022 landed (the newest job log is 2026-07-31, before it), so nothing has *yet* rendered as prose because of this — but the first default-settings render would, silently.

## Root cause

Ollama's default bind is loopback. The systemd unit sets only `PATH`; no
`OLLAMA_HOST`. The compose `extra_hosts` mapping resolves the name correctly —
the socket simply is not listening on that interface.

## Fix (host, needs sudo — Kevin)

```bash
sudo systemctl edit ollama
# add:
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
# then:
sudo systemctl daemon-reload && sudo systemctl restart ollama
ss -ltn | grep 11434          # → 0.0.0.0:11434
```

Safe to do whenever `ollama ps` is empty (nothing resident). Binding all
interfaces exposes Ollama to the LAN with no auth — the same posture as every
other service on this box.

## Acceptance criteria

- [ ] `ss -ltn` shows Ollama on `0.0.0.0:11434` (or the bridge IP)
- [ ] `docker compose exec gateway python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/version').json())"` prints a version
- [ ] Same from `flow`
- [ ] A default-settings `/generate` reports `prompt_source: "upsampled"` — STORY_022's open acceptance box can be ticked
- [ ] `POST /agent/plan` returns scripts (STORY_029 E2E)

## Resolution

_(pending)_
