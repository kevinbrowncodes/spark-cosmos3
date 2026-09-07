#!/usr/bin/env bash
# flow_agent.sh — drive the scene agent from a terminal (STORY_031).
#
#   scripts/flow_agent.sh skills
#   scripts/flow_agent.sh plan    <seed> <skill> [count]                 # dry run: prints the scripts, renders nothing
#   scripts/flow_agent.sh run     <seed> <skill> [count] [--zero-shot] [--size WxH] [--length N] [--project ID]
#   scripts/flow_agent.sh show    <run>
#   scripts/flow_agent.sh edit    <run> <n>                              # $EDITOR on script n, PATCH on save
#   scripts/flow_agent.sh rewrite <run> <n>
#   scripts/flow_agent.sh approve <run>
#   scripts/flow_agent.sh resume  <run>
#   scripts/flow_agent.sh watch   <run>                                  # exits 0 on done, 1 on failed
#   scripts/flow_agent.sh list
#
# <seed> is a media id (in:…, out:…) or a local image/video file, which is uploaded first.
# FLOW_URL (default http://localhost:8003) selects the sidecar. The memory check mirrors the
# executor's gate (AGENT_MIN_FREE_GIB, default 30) so you hear about a shortfall before you walk away.
set -euo pipefail
BASE="${FLOW_URL:-http://localhost:8003}"
MIN_GIB="${AGENT_MIN_FREE_GIB:-30}"

die() { echo "error: $*" >&2; exit 2; }

# call METHOD PATH [JSON] → prints the body; exits 2 with the server's detail on a non-2xx
call() {
  local m=$1 p=$2 body=${3:-} out code
  if [ -n "$body" ]; then out=$(curl -sS -X "$m" "$BASE$p" -H 'content-type: application/json' -d "$body" -w $'\n%{http_code}')
  else out=$(curl -sS -X "$m" "$BASE$p" -w $'\n%{http_code}'); fi
  code=${out##*$'\n'}; body=${out%$'\n'*}
  case $code in 2*) printf '%s' "$body";;
    *) die "$m $p → $code: $(BODY="$body" python3 - <<'PY'
import json, os
try: print(json.loads(os.environ["BODY"]).get("detail"))
except Exception: print(os.environ["BODY"][:300])
PY
)";; esac
}

gate() {
  local avail; avail=$(awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo)
  if [ "$avail" -lt "$MIN_GIB" ]; then
    echo "memory gate: $avail GiB available, need $MIN_GIB — the executor would pause this run at its first clip." >&2
    echo "free memory (or lower AGENT_MIN_FREE_GIB) before starting." >&2; exit 3
  fi
}

seed_id() {  # a media id as-is, or upload a file and print its id
  if [ -f "$1" ]; then
    curl -fsS -F "file=@$1" "$BASE/flow/uploads" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
  else printf '%s' "$1"; fi
}

show_run() {
  RUN="$1" python3 - <<'PY'
import json, os
r = json.loads(os.environ["RUN"])
v = r["values"]
print(f'{r["id"]}  {r["state"]:9}  {r["step"]}')
print(f'  {r["title"]}  ·  {r["instruction"]} × {r["count"]}  ·  {v["size"]} · {v["length"]} s  ·  seed {r["reference_id"]}')
if r.get("error"): print(f'  error: {r["error"]}')
for c in r["clips"]:
    prog = f' {c["progress"]}%' if c.get("progress") is not None else ""
    print(f'  clip {c["n"]}: {c["status"]}{prog}  {c.get("media_id") or c.get("job_id") or ""}')
    if c.get("script"): print("     " + c["script"].replace("\n", "\n     "))
if r.get("summary"): print("\n" + r["summary"])
PY
}

run_id_of() { RUN="$1" python3 -c 'import json,os; print(json.loads(os.environ["RUN"])["id"])'; }

cmd=${1:-}; shift || true
case "$cmd" in
  skills)
    OUT="$(call GET /agent/instructions)" python3 - <<'PY'
import json, os
for s in json.loads(os.environ["OUT"]):
    print(f'{s["id"]:40} {"1 clip" if s["count_locked"] else "N clips":8} {s["description"]}')
PY
    ;;

  plan)
    [ $# -ge 2 ] || die "plan <seed> <skill> [count]"
    id=$(seed_id "$1")
    body=$(SEED="$id" SKILL="$2" COUNT="${3:-1}" python3 -c 'import json,os; print(json.dumps({"reference_id":os.environ["SEED"],"instruction":os.environ["SKILL"],"count":int(os.environ["COUNT"])}))')
    echo "planning ${3:-1} script(s) with $2 from $id … (Gemma, ~2 min)" >&2
    OUT="$(call POST /agent/plan "$body")" python3 - <<'PY'
import json, os, sys
p = json.loads(os.environ["OUT"])
for i, s in enumerate(p["scripts"], 1): print(f"<<<SCRIPT {i}>>>\n{s}\n<<<END SCRIPT>>>\n")
if p["titles"]: print("TITLES:\n  " + "\n  ".join(p["titles"]))
if p.get("summary"): print("\nSUMMARY:\n" + p["summary"])
print(f'\n({p["attempts"]} attempt(s), {p["model"]}; nothing rendered)', file=sys.stderr)
PY
    ;;

  run)
    [ $# -ge 2 ] || die "run <seed> <skill> [count] [--zero-shot] [--size WxH] [--length N] [--project ID]"
    seed=$1; skill=$2; shift 2; count=1; zero=false; size=""; length=""; project=""
    while [ $# -gt 0 ]; do case $1 in
      --zero-shot) zero=true;; --size) size=$2; shift;; --length) length=$2; shift;; --project) project=$2; shift;;
      [0-9]*) count=$1;; *) die "unknown option $1";; esac; shift; done
    gate
    id=$(seed_id "$seed")
    body=$(SEED="$id" SKILL="$skill" COUNT="$count" ZERO="$zero" SIZE="$size" LENGTH="$length" PROJECT="$project" python3 - <<'PY'
import json, os
v = {}
if os.environ["SIZE"]: v["size"] = os.environ["SIZE"]
if os.environ["LENGTH"]: v["length"] = int(os.environ["LENGTH"])
print(json.dumps({"reference_id": os.environ["SEED"], "instruction": os.environ["SKILL"], "count": int(os.environ["COUNT"]),
                  "values": v, "autostart": os.environ["ZERO"] == "true", "project_id": os.environ["PROJECT"] or None}))
PY
)
    run=$(call POST /agent/runs "$body"); show_run "$run"; rid=$(run_id_of "$run")
    if $zero; then echo "zero-shot: renders as soon as the plan exists.  watch: $0 watch $rid" >&2
    else echo "next: $0 show $rid   (edit/rewrite as needed, then: $0 approve $rid)" >&2; fi ;;

  show)   [ $# -ge 1 ] || die "show <run>"; show_run "$(call GET "/agent/runs/$1")" ;;
  list)
    OUT="$(call GET /agent/runs)" python3 - <<'PY'
import json, os, time
for r in json.loads(os.environ["OUT"]):
    print(f'{r["id"]}  {r["state"]:9}  {time.strftime("%m-%d %H:%M", time.localtime(r["created_at"]))}  {r["title"]}  —  {r["step"]}')
PY
    ;;

  edit)
    [ $# -ge 2 ] || die "edit <run> <n>"
    tmp=$(mktemp --suffix=.txt); trap 'rm -f "$tmp"' EXIT
    RUN="$(call GET "/agent/runs/$1")" N="$2" python3 -c 'import json,os; print(json.loads(os.environ["RUN"])["scripts"][int(os.environ["N"])-1])' > "$tmp"
    "${EDITOR:-vi}" "$tmp"
    body=$(TEXT="$(cat "$tmp")" python3 -c 'import json,os; print(json.dumps({"text": os.environ["TEXT"]}))')
    show_run "$(call PATCH "/agent/runs/$1/scripts/$2" "$body")" ;;

  rewrite) [ $# -ge 2 ] || die "rewrite <run> <n>"; echo "rewriting script $2 … (Gemma, ~2 min)" >&2
           show_run "$(call POST "/agent/runs/$1/scripts/$2/rewrite")" ;;
  approve) [ $# -ge 1 ] || die "approve <run>"; gate; show_run "$(call POST "/agent/runs/$1/approve")"; echo "watch: $0 watch $1" >&2 ;;
  resume)  [ $# -ge 1 ] || die "resume <run>"; show_run "$(call POST "/agent/runs/$1/resume")" ;;

  watch)
    [ $# -ge 1 ] || die "watch <run>"; start=$(date +%s)
    while :; do
      run=$(call GET "/agent/runs/$1")
      line=$(RUN="$run" ELAPSED=$(( $(date +%s) - start )) python3 - <<'PY'
import json, os
r = json.loads(os.environ["RUN"]); e = int(os.environ["ELAPSED"])
cur = r["clips"][min(r["clip_index"], r["count"] - 1)]
prog = f' · {cur["progress"]} %' if r["state"] == "rendering" and cur.get("progress") is not None else ""
print(f'{r["id"]} · {r["step"]}{prog} · {e//3600:02d}:{e%3600//60:02d}:{e%60:02d}   [{r["state"]}]')
PY
)
      printf '\r\033[K%s' "$line"
      state=${line##*[}; state=${state%]}
      case $state in
        done)   echo; RUN="$run" python3 -c 'import json,os; [print(c["media_id"]) for c in json.loads(os.environ["RUN"])["clips"]]'; exit 0;;
        failed) echo; RUN="$run" python3 -c 'import json,os; print("error:", json.loads(os.environ["RUN"])["error"])' >&2; exit 1;;
      esac
      sleep 15
    done ;;

  ""|-h|--help|help) sed -n '2,16p' "$0";;
  *) die "unknown command $cmd (try: $0 help)";;
esac
