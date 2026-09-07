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
CAPS="$caps" python3 - <<'PY2' || fail "capabilities: STORY_024 field shape"
import json, os
caps = json.loads(os.environ["CAPS"])
assert caps["reference_kinds"] == ["image", "video"], caps["reference_kinds"]      # STORY_026: Extend
fields = {f["key"]: f for f in caps["modes"][0]["fields"]}
assert "frames" not in fields, "frames control must be gone"
length = fields["length"]
assert length["role"] == "duration" and [o["value"] for o in length["options"]] == [5, 8, 10] and length["default"] == 8, length
assert [o["value"] for o in fields["count"]["options"]] == [1], fields["count"]
PY2
ok "capabilities: length 5/8/10 s (role duration), count [1], no frames, reference_kinds image+video"

for path in /flow/ /ui/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE$path")
  [ "$code" = 200 ] || fail "GET $path → $code"
  curl -sI "$BASE$path" | grep -qi '^content-type: text/html' || fail "GET $path is not text/html"
  curl -s "$BASE$path" | grep -q 'randomUUID=function' || fail "GET $path lacks the crypto.randomUUID shim (BUG_005)"
  ok "GET $path → 200 text/html, shim present"
done
# STORY_028: the served bundle is the one with the projects home (v0.2.0+): its main
# script carries the home page's markers, not just a 200 shell.
js=$(curl -s "$BASE/flow/" | grep -o 'src="[^"]*\.js"' | head -1 | sed 's/src="//; s/"$//')
[ -n "$js" ] || fail "GET /flow/ has no script tag"
case "$js" in /*) jsurl="$BASE$js";; *) jsurl="$BASE/flow/$js";; esac
bundle=$(curl -fsS "$jsurl") || fail "GET $jsurl"
echo "$bundle" | grep -q 'New project' || fail "bundle lacks the projects home (no 'New project')"
echo "$bundle" | grep -q 'projects-grid' || fail "bundle lacks the projects grid marker"
ok "GET /flow/ serves the projects home bundle ($js)"
loc=$(curl -s -o /dev/null -w '%{redirect_url}' "$BASE/")
[[ "$loc" == */flow/ ]] || fail "GET / does not redirect to /flow/ (got '$loc')"
ok "GET / → /flow/"

resp=$(curl -s -w '\n%{http_code}' "$BASE/flow/jobs/does-not-exist")
[ "${resp##*$'\n'}" = 404 ] || fail "unknown job → ${resp##*$'\n'}"
echo "$resp" | head -1 | grep -q '"detail"' || fail "404 body has no detail"
ok "GET /flow/jobs/{unknown} → 404 with detail"

instr=$(curl -fsS "$BASE/agent/instructions") || fail "GET /agent/instructions"
INSTR="$instr" python3 - <<'PY2' || fail "agent instructions shape"
import json, os
rows = json.loads(os.environ["INSTR"])
assert isinstance(rows, list), rows
for r in rows:
    assert set(r) == {"id", "name", "description", "count_locked"}, r
print(f"  {len(rows)} skill(s): " + ", ".join(r["id"] for r in rows))
PY2
ok "GET /agent/instructions → 200, valid array (STORY_029)"
runs=$(curl -fsS "$BASE/agent/runs") || fail "GET /agent/runs"
echo "$runs" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert isinstance(r, list), r; print(f"  {len(r)} run(s)")' || fail "agent runs shape"
ok "GET /agent/runs → 200, valid array (STORY_030)"

# STORY_032: the protocol mirror exists only once the pinned flow-protocol knows Agent mode.
if echo "$caps" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("agent") else 1)'; then
  curl -fsS "$BASE/flow/agent/instructions" >/dev/null || fail "GET /flow/agent/instructions (agent declared)"
  ok "capabilities.agent declared and /flow/agent/* answers (STORY_032)"
else
  echo "! capabilities.agent not declared — flow-protocol in this image predates Agent mode (bump FLOW_VERSION)"
fi

label=$(docker inspect spark-cosmos3-flow:latest --format '{{ index .Config.Labels "git.sha" }}' 2>/dev/null || true)
head=$(git rev-parse --short HEAD 2>/dev/null || true)
if [ -n "$label" ] && [ "$label" = "$head" ]; then
  ok "image git.sha $label matches HEAD"
else
  echo "! image git.sha='${label:-none}' HEAD='${head:-?}' — rebuild with scripts/deploy.sh after committing"
fi
echo "contract checks passed"
