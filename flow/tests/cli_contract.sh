#!/usr/bin/env bash
# CLI contract (STORY_031): the wrapper against the RUNNING sidecar. Plans only when Ollama is reachable.
set -euo pipefail
cd "$(dirname "$0")/../.."
CLI=scripts/flow_agent.sh
ok()   { echo "✓ $1"; }
fail() { echo "✗ $1"; exit 1; }

$CLI help | grep -q "flow_agent.sh skills" || fail "help"
ok "help prints usage"
$CLI skills | grep -q "example-forecast-scene" || fail "skills lists the example skill"
ok "skills lists the library"
$CLI list >/dev/null || fail "list"
ok "list runs"
$CLI bogus >/dev/null 2>&1 && fail "unknown command should exit non-zero" || ok "unknown command exits non-zero"
$CLI show run_doesnotexist >/dev/null 2>&1 && fail "show of an unknown run should exit non-zero" || ok "show of an unknown run → error"

if docker compose exec -T flow python -c "import os, httpx; httpx.get(os.environ['GEMMA_URL'] + '/api/version', timeout=3)" >/dev/null 2>&1; then
  before=$(curl -s localhost:8003/flow/media | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
  out=$($CLI plan "$HOME/Documents/cosmos-media/input_cap_guy.jpg" example-forecast-scene 1 2>/dev/null) || fail "plan (Gemma reachable)"
  echo "$out" | grep -q "<<<SCRIPT 1>>>" || fail "plan printed no script"
  after=$(curl -s localhost:8003/flow/media | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
  [ "$after" -eq $((before + 1)) ] || fail "plan should add exactly the uploaded seed to media, nothing else (before=$before after=$after)"
  ok "plan: one script from Gemma, nothing rendered"
else
  echo "! plan: SKIPPED — Ollama not reachable from the sidecar (BUG_006)"
fi
echo "cli contract passed"
