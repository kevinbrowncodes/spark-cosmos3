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
echo "$caps" | python3 - <<'PY2' || fail "capabilities: STORY_024 field shape"
import json, sys
fields = {f["key"]: f for f in json.load(sys.stdin)["modes"][0]["fields"]}
assert "frames" not in fields, "frames control must be gone"
length = fields["length"]
assert length["role"] == "duration" and [o["value"] for o in length["options"]] == [5, 8, 10] and length["default"] == 8, length
assert [o["value"] for o in fields["count"]["options"]] == [1], fields["count"]
PY2
ok "capabilities: length 5/8/10 s (role duration), count [1], no frames"

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
