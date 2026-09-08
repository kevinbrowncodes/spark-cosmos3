"""Overnight supervisor for the two 30-second runs (project overnight-2026-09-07).

Handles the failure modes seen on 2026-09-07 so nobody has to be awake for them:
  * paused on the memory gate after a 720p clip (BUG_010) -> restart the idle engine, wait for
    health, let the executor resubmit; if that submit raced the reload and failed, resume.
  * failed with a gateway 500 / connection error (the engine was still loading) -> wait for
    health, resume. Up to MAX_RESUMES per run.
  * a run that keeps failing -> replace it with the same seed and skill at 832x480, which
    completed cleanly today, so there is still a clip in the morning.
  * done -> join the three clips into one 30 s file next to them (flow-outputs), so the whole
    scene is one download.
Logs every action with a timestamp. Exits when every run is done and stitched, or after 10 h.
"""
import json, subprocess, time, urllib.request, urllib.error
from pathlib import Path

API = "http://localhost:8003"
PROJECT = "overnight-2026-09-07"
OUT = Path.home() / "Documents/flow-media/flow-outputs"
RUNS = Path.home() / "Documents/flow-media/flow-runs"
COMPOSE = Path.home() / "Documents/GitHub/kevinbrowncodes/spark-cosmos3/docker-compose.yml"
MAX_RESUMES = 5
MAX_RESTARTS = 8
DEADLINE = time.time() + 10 * 3600

resumes: dict[str, int] = {}
restarts = 0
replaced: set[str] = set()
stitched: set[str] = set()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(path):
    with urllib.request.urlopen(API + path, timeout=30) as r:
        return json.load(r)


def post(path, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(API + path, data=data, method="POST", headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def engine_healthy():
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=5)
        return True
    except Exception:
        return False


def mem_gib():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable"):
            return int(line.split()[1]) / 1048576
    return 0.0


def wait_healthy(label):
    t0 = time.time()
    while not engine_healthy():
        if time.time() - t0 > 900:
            log(f"{label}: engine not healthy after 15 min; giving up this round")
            return False
        time.sleep(15)
    time.sleep(30)          # let the gateway see it and memory settle; resuming at +12 s failed today
    log(f"{label}: engine healthy after {int(time.time() - t0)} s, {mem_gib():.1f} GiB available")
    return True


def restart_engine(reason):
    global restarts
    if restarts >= MAX_RESTARTS:
        log(f"restart budget exhausted ({MAX_RESTARTS}); not restarting for: {reason}")
        return False
    restarts += 1
    log(f"restarting the engine ({restarts}/{MAX_RESTARTS}): {reason}; {mem_gib():.1f} GiB available")
    subprocess.run(["docker", "compose", "-f", str(COMPOSE), "restart", "cosmos3"], capture_output=True, timeout=600)
    return wait_healthy("restart")


def resume(run):
    n = resumes.get(run["id"], 0)
    if n >= MAX_RESUMES:
        return False
    resumes[run["id"]] = n + 1
    try:
        r = post(f"/agent/runs/{run['id']}/resume")
        log(f"{run['id']}: resumed ({n + 1}/{MAX_RESUMES}) -> {r.get('state')} | {r.get('step')}")
        return True
    except urllib.error.HTTPError as e:
        log(f"{run['id']}: resume refused {e.code}: {e.read()[:120]!r}")
        return False


def replace(run):
    if run["id"] in replaced:
        return
    replaced.add(run["id"])
    body = {"reference_id": run["reference_id"], "instruction": run["instruction"], "count": run["count"],
            "values": {**run["values"], "size": "832x480"}, "autostart": True, "project_id": PROJECT}
    body["values"].pop("count", None)
    r = post("/agent/runs", body)
    log(f"{run['id']}: gave up after {MAX_RESUMES} resumes; replaced by {r['id']} at {r['values']['size']} (BUG_010 fallback)")


def stitch(run):
    if run["id"] in stitched:
        return
    clips = [OUT / c["media_id"].split(":", 1)[1] for c in run["clips"] if c.get("media_id")]
    if len(clips) != run["count"] or not all(p.exists() for p in clips):
        log(f"{run['id']}: done but clips missing on disk: {[p.name for p in clips]}")
        stitched.add(run["id"])
        return
    listing = Path(f"/tmp/{run['id']}-concat.txt")
    listing.write_text("".join(f"file '{p}'\n" for p in clips))
    out = OUT / f"{run['id']}_full.mp4"
    tmp = out.with_suffix(".part")
    proc = subprocess.run(["nice", "-n", "10", "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                           "-i", str(listing), "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                           "-r", "24", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", str(tmp)],
                          capture_output=True, timeout=1800)
    if proc.returncode == 0 and tmp.exists():
        tmp.replace(out)
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                             capture_output=True, text=True).stdout.strip()
        log(f"{run['id']}: stitched {len(clips)} clips -> {out.name} ({dur} s) — '{run.get('title')}'")
    else:
        log(f"{run['id']}: stitch failed: {proc.stderr.decode(errors='replace')[:300]}")
    stitched.add(run["id"])


def tick():
    runs = [r for r in get("/agent/runs") if r.get("project_id") == PROJECT]
    active = [r for r in runs if r["id"] not in replaced]
    states = {r["id"]: (r["state"], r["step"]) for r in active}
    for r in active:
        st = r["state"]
        if st == "done":
            stitch(r)
        elif st == "paused":
            if any(x["state"] == "rendering" for x in active):
                continue                                    # something else is using the engine; wait
            if engine_healthy():
                if restart_engine(f"{r['id']} paused: {r.get('error')}"):
                    time.sleep(20)
                    fresh = get(f"/agent/runs/{r['id']}")
                    if fresh["state"] in ("paused", "failed"):
                        resume(fresh)
            else:
                wait_healthy(r["id"]) and resume(r)
        elif st == "failed":
            err = (r.get("error") or "").lower()
            transient = any(k in err for k in ("internal server error", "connect", "gateway", "reset", "timed out", "gone"))
            if transient and resumes.get(r["id"], 0) < MAX_RESUMES:
                wait_healthy(r["id"]) and resume(r)
            else:
                replace(r)
    return states


last = None
log(f"supervising project {PROJECT}; engine healthy={engine_healthy()}, {mem_gib():.1f} GiB available")
while time.time() < DEADLINE:
    try:
        states = tick()
        if states != last:
            log("state: " + "; ".join(f"{k} {v[0]} ({v[1][:36]})" for k, v in states.items()))
            last = states
        live = [k for k, v in states.items()]
        if live and all(get(f"/agent/runs/{k}")["state"] == "done" and k in stitched for k in live):
            log("every run is done and stitched; supervisor exiting")
            break
    except Exception as e:                                   # keep supervising through any one bad poll
        log(f"tick error: {e!r}")
    time.sleep(60)
log("supervisor finished")
