#!/usr/bin/env bash
# The three real renders behind EPIC_002 (STORY_025 ×2, STORY_026), gated on
# memory. Each phase can be run alone: ./scripts/flow_e2e_renders.sh [conformance|ui|extend|all]
#
# Gate (CLAUDE.md §7 + 2026-09-06 decision): ≥ 30 GiB available on top of the
# resident engine and no NVRM out-of-memory line in today's kernel log.
# Never frees memory itself — stopping spark-primary/hermes is Kevin's call.
set -euo pipefail
cd "$(dirname "$0")/.."
PHASE="${1:-all}"
STILL="${STILL:-$HOME/Documents/cosmos-media/input_cap_guy.jpg}"
MEDIA="${FLOW_MEDIA_DIR:-$HOME/Documents/flow-media}"
BASE="http://localhost:8003"
PY=".venv/bin/python"

gate() {
  local avail_gib oom
  avail_gib=$(awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo)
  # Count OOM lines since the ENGINE started, not "today": an OOM before the current engine
  # incarnation describes a machine state that no longer exists, and one stale line would
  # otherwise block every render for the rest of the day (seen 2026-09-07, BUG_010).
  local since; since=$(docker inspect -f '{{.State.StartedAt}}' cosmos3-api 2>/dev/null || true)
  since=$([ -n "$since" ] && date -d "$since" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo today)
  oom=$(journalctl -k --since "$since" 2>/dev/null | grep -ci "out of memory" || true)
  echo "memory gate: OOM window starts $since (engine start)"
  echo "memory gate: ${avail_gib} GiB available, ${oom} NVRM/OOM line(s) since then"
  # Same threshold the agent's executor uses on this box (.env AGENT_MIN_FREE_GIB, default 30):
  # a 720x1280 clip rendered cleanly from 22.9 GiB available on 2026-09-07 (BUG_010 notes).
  local min_gib; min_gib=$(sed -n 's/^AGENT_MIN_FREE_GIB=//p' .env 2>/dev/null | tail -1); min_gib=${AGENT_MIN_FREE_GIB:-${min_gib:-30}}
  if [ "$avail_gib" -lt "$min_gib" ] || [ "$oom" -gt 0 ]; then
    echo "ABORT: gate tripped (need ≥ ${min_gib} GiB and 0 OOM lines). Nothing submitted." >&2
    exit 2
  fi
  if [ -n "$(ls -t data/logs/jobs 2>/dev/null | head -1)" ]; then
    local last id st
    last=$(ls -t data/logs/jobs | head -1); id=${last#*_}; id=${id%.json}
    st=$(curl -s "localhost:8002/jobs/$id" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo unknown)
    echo "last gateway job $id: $st"
    case "$st" in queued|in_progress) echo "ABORT: a render is in flight." >&2; exit 2;; esac
  fi
}

phase_conformance() {   # STORY_025: the protocol path, exactly what the UI sends
  mkdir -p docs/evidence/STORY_025
  cp -n "$STILL" "$MEDIA/$(basename "$STILL")" 2>/dev/null || true
  docker compose exec -T flow flow-conformance "$BASE" --generate --reference "/media/$(basename "$STILL")" --timeout 3600 \
    | tee docs/evidence/STORY_025/conformance-generate.txt
}

phase_home() {          # STORY_028: the projects home page, no render (~30 s)
  "$PY" flow/tests/e2e_ui_home.py --base "${UI_BASE:-http://192.168.1.33:8003}" \
    | tee docs/evidence/story-028-home-page/verify-phase-a.txt
}

phase_ui() {            # STORY_025: a person's click path, in headless Chromium
  "$PY" flow/tests/e2e_ui_generate.py --still "$STILL" --out docs/evidence/STORY_025 --submit --timeout 3600 \
    ${UI_STATE:+--state "$UI_STATE"} \
    --prompt "A man in a cap looks up from his work and grins as sunlight moves across the room." \
    | tee docs/evidence/STORY_025/ui-generate.txt
}

phase_extend() {        # STORY_026: extend the newest cached clip at 480p, Length 10
  mkdir -p docs/evidence/STORY_026
  local src job id st
  src=$(curl -s "$BASE/flow/media" | python3 -c 'import json,sys; a=[x for x in json.load(sys.stdin) if x["kind"]=="video" and x["source"]=="output"]; print(a[0]["id"] if a else "")')
  [ -n "$src" ] || { echo "no cached output to extend — run the ui/conformance phase first" >&2; exit 1; }
  echo "extending $src"
  job=$(curl -s -X POST "$BASE/flow/generate" -H 'content-type: application/json' -d "$(python3 -c "import json;print(json.dumps({'mode':'video','prompt':'The scene continues: he turns toward the window, the light settling on his face.','values':{'size':'832x480','length':10,'steps':35,'sound':True,'upsample':True,'reasoner':'gemma','count':1},'reference_id':'$src'}))")")
  echo "$job" | tee docs/evidence/STORY_026/generate.json
  id=$(echo "$job" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
  while :; do
    st=$(curl -s "$BASE/flow/jobs/$id"); echo "$(date +%H:%M:%S) $st" | tail -c 200
    case "$(echo "$st" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')" in done) break;; failed) echo "extend FAILED" >&2; exit 1;; esac
    sleep 30
  done
  echo "--- served (must be 10.0 s) ---"; ffprobe -v error -show_entries format=duration -of csv=p=0 "$MEDIA/flow-outputs/$id.mp4" | tee docs/evidence/STORY_026/served-duration.txt
  echo "--- raw frames (must be 313) ---"; ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of csv=p=0 "$MEDIA/flow-outputs-raw/$id.mp4" | tee docs/evidence/STORY_026/raw-frames.txt
}

gate
case "$PHASE" in
  conformance) phase_conformance;;
  home) phase_home;;
  ui) phase_ui;;
  extend) phase_extend;;
  all) phase_conformance; phase_home; gate; phase_ui; gate; phase_extend;;
  *) echo "usage: $0 [conformance|home|ui|extend|all]" >&2; exit 64;;
esac
echo "done: $PHASE"
