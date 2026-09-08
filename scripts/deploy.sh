#!/usr/bin/env bash
# Build and start the gateway, progress-sidecar and flow sidecar with the current git SHA
# baked in as a Docker label, then start (or restart) the full stack.
#
# Usage: ./scripts/deploy.sh [--force]
#
# Refuses while something is mid-render, because recreating the flow container drops every
# connection into it: a conformance or E2E client polling /flow/jobs/{id} dies with
# ECONNRESET while the engine keeps rendering for nobody (BUG_013). --force overrides, for
# when the sidecar is itself what is broken.
#
# To verify after deploy:
#   docker inspect spark-cosmos3-gateway:latest | python3 -c \
#     "import sys,json; d=json.load(sys.stdin); print(d[0]['Config']['Labels'])"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

FORCE=false
[ "${1:-}" = "--force" ] && FORCE=true

busy() {   # BUG_013: never recreate the sidecar out from under a running check
  local rendering last id st
  rendering=$(curl -s --max-time 5 localhost:8003/agent/runs 2>/dev/null \
    | python3 -c 'import json,sys; print(sum(1 for r in json.load(sys.stdin) if r.get("state")=="rendering"))' 2>/dev/null || echo 0)
  [ "${rendering:-0}" -gt 0 ] && { echo "an agent run is rendering"; return 0; }
  last=$(set +o pipefail; ls -t data/logs/jobs 2>/dev/null | head -1)
  [ -n "$last" ] || return 1
  id=${last#*_}; id=${id%.json}
  st=$(curl -s --max-time 5 "localhost:8002/jobs/$id" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo unknown)
  case "$st" in queued|in_progress) echo "gateway job $id is $st"; return 0;; esac
  return 1
}

if reason=$(busy); then
  if $FORCE; then
    echo "WARNING: $reason — deploying anyway (--force); any client polling the sidecar will drop"
  else
    echo "ABORT: $reason. Recreating the sidecar would drop it (BUG_013)." >&2
    echo "       Wait, or re-run with --force if the sidecar is what needs fixing." >&2
    exit 2
  fi
fi

export GIT_SHA
GIT_SHA=$(git rev-parse --short HEAD)

echo "Deploying spark-cosmos3 @ $GIT_SHA ..."
docker compose up -d --build --no-deps gateway progress flow
docker compose up -d cosmos3

echo
echo "Done. Verify labels:"
echo "  Gateway : $(docker inspect spark-cosmos3-gateway:latest | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Labels'])")"
echo "  Progress: $(docker inspect spark-cosmos3-progress:latest | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Labels'])")"
echo "  Flow    : $(docker inspect spark-cosmos3-flow:latest | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Labels'])")"
