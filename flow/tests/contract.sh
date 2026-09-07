#!/usr/bin/env bash
# Contract checks against the RUNNING flow container (STORY_023).
#   flow/tests/contract.sh [http://localhost:8003]
set -euo pipefail
BASE="${1:-http://localhost:8003}"
ok()   { echo "✓ $1"; }
fail() { echo "✗ $1"; exit 1; }

caps=$(curl -fsS "$BASE/flow/capabilities") || fail "GET /flow/capabilities"
echo "$caps" | python3 -c 'import json,sys; c=json.load(sys.stdin); assert c["protocol"]==1, c; assert c["name"]=="Cosmos 3 Nano", c' \
  || fail "capabilities: protocol/name"
ok "GET /flow/capabilities → 200, protocol 1, Cosmos 3 Nano"

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/ui/")
[ "$code" = 200 ] || fail "GET /ui/ → $code"
curl -sI "$BASE/ui/" | grep -qi '^content-type: text/html' || fail "GET /ui/ is not text/html"
ok "GET /ui/ → 200 text/html"

resp=$(curl -s -w '\n%{http_code}' "$BASE/flow/jobs/does-not-exist")
[ "${resp##*$'\n'}" = 404 ] || fail "unknown job → ${resp##*$'\n'}"
echo "$resp" | head -1 | grep -q '"detail"' || fail "404 body has no detail"
ok "GET /flow/jobs/{unknown} → 404 with detail"

label=$(docker inspect spark-cosmos3-flow:latest --format '{{ index .Config.Labels "git.sha" }}' 2>/dev/null || true)
head=$(git rev-parse --short HEAD 2>/dev/null || true)
if [ -n "$label" ] && [ "$label" = "$head" ]; then
  ok "image git.sha $label matches HEAD"
else
  echo "! image git.sha='${label:-none}' HEAD='${head:-?}' — rebuild with scripts/deploy.sh after committing"
fi
echo "contract checks passed"
