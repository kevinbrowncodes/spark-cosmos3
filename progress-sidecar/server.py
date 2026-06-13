"""Progress sidecar for cosmos3-api.

vLLM-Omni's /v1/videos status endpoint never updates `progress` during
generation (verified against vllm-omni 0.21.0 and upstream main, 2026-06-12).
The real per-step progress only exists in the container logs as a tqdm bar:

    24%|##4       | 12/50 [09:12<29:08, 46.11s/it]

This sidecar follows the cosmos3-api container logs via the Docker socket,
parses the most recent denoise step, and serves it as JSON:

    GET /progress -> {"active": true, "video_id": "video_gen_...",
                      "step": 12, "total": 50, "percent": 24,
                      "seconds_per_step": 46.11, "eta_s": 1752.2,
                      "age_s": 3.1}
    GET /health   -> 200

Notes:
- Cosmos serves one generation at a time on this box, so "latest tqdm line"
  is the progress of the current job. video_id is best-effort, taken from the
  most recent job id seen in the API access logs.
- `active` means: denoise not finished AND the last update is fresh
  (< STALE_S). After the last step the server still spends minutes in
  VAE/audio/encode — clients should treat step==total as "finishing".
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import docker

TARGET = os.environ.get("COSMOS_CONTAINER", "cosmos3-api")
PORT = int(os.environ.get("PORT", "8001"))
STALE_S = float(os.environ.get("STALE_S", "180"))

# tqdm:  24%|##4       | 12/50 [09:12<29:08, 46.11s/it]
TQDM_RE = re.compile(
    r"(\d+)%\|[^|]*\|\s*(\d+)/(\d+)\s*\[[\d:]+<[\d:?.]+(?:,\s*([\d.]+)s/it)?"
)
VID_RE = re.compile(r"video_gen_[0-9a-f]{32}")
# Lines that also contain tqdm bars but are not denoising progress.
EXCLUDE = ("shard", "Loading", "Fetching")

_state: dict = {}
_lock = threading.Lock()
_last_ts: float | None = None


def _parse_ts(ts: str) -> float:
    # Docker timestamps: 2026-06-12T18:30:01.123456789Z — trim to microseconds.
    ts = ts.rstrip("Z")
    if "." in ts:
        head, frac = ts.split(".", 1)
        ts = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp()


def _handle_line(line: str) -> None:
    # Records normally start with a Docker timestamp, but tqdm refreshes are
    # \r-separated *within* a record, so the bar text arrives with no
    # timestamp of its own — carry the last seen timestamp forward.
    global _last_ts
    ts = None
    parts = line.split(" ", 1)
    if parts:
        try:
            ts = _parse_ts(parts[0])
            _last_ts = ts
            payload = parts[1] if len(parts) == 2 else ""
        except ValueError:
            payload = line
            ts = _last_ts
    if ts is None or not payload:
        return

    vid = VID_RE.search(payload)
    # Don't learn job ids from failed lookups (404/405 probes of old jobs
    # would steal attribution from the actually-running job).
    if vid and '" 404' not in payload and '" 405' not in payload:
        with _lock:
            if _state.get("video_id") != vid.group(0):
                _state["video_id"] = vid.group(0)
                # New job: drop the previous job's bar so its last step is
                # never attributed to this one. The new job's own bars
                # repopulate within one tqdm refresh. (Replaces the old
                # timestamp-comparison stale-guard, which nulled live renders
                # because the bar's docker timestamp is frozen at denoise
                # start — see the bar_wall note below.)
                for k in ("step", "total", "percent", "seconds_per_step", "bar_wall"):
                    _state.pop(k, None)

    if any(word in payload for word in EXCLUDE):
        return
    m = TQDM_RE.search(payload)
    if not m:
        return
    percent, step, total, s_per_it = m.groups()
    if int(total) <= 1:  # warmup/no-op bars, not the denoise loop
        return
    with _lock:
        _state.update(
            {
                "percent": int(percent),
                "step": int(step),
                "total": int(total),
                "seconds_per_step": float(s_per_it) if s_per_it else None,
                # Freshness is wall-clock at receipt, NOT the docker log
                # timestamp: tqdm refreshes the whole bar via \r inside ONE log
                # record, so every step shares that record's start-time stamp
                # (using it, a render looks minutes stale within a step or two).
                # NOTE: docker only delivers that record once it is newline-
                # terminated — i.e. at the END of denoise — so in practice this
                # whole block runs in a burst when the bar finishes, not live
                # per step. The sidecar is a terminal/tail signal, not a live
                # progress source (see docs/api.md). PYTHONUNBUFFERED does not
                # change this; it governs Python's buffer, not docker framing.
                "bar_wall": time.time(),
            }
        )


def _follow_logs() -> None:
    while True:
        try:
            client = docker.from_env()
            container = client.containers.get(TARGET)
            buf = b""
            for chunk in container.logs(
                stream=True, follow=True, tail=500, timestamps=True
            ):
                buf += chunk
                # Records are delimited by \n; tqdm refreshes arrive as \r
                # updates — treat both as line breaks.
                *lines, buf = re.split(rb"[\r\n]", buf)
                for raw in lines:
                    if raw.strip():
                        _handle_line(raw.decode("utf-8", "replace"))
        except Exception as exc:  # container restarting, socket hiccup, …
            print(f"sidecar: log follow error, retrying in 5s: {exc}", flush=True)
            time.sleep(5)


def _snapshot() -> dict:
    with _lock:
        s = dict(_state)
    now = time.time()
    age = now - s["bar_wall"] if "bar_wall" in s else None
    step, total = s.get("step"), s.get("total")
    sps = s.get("seconds_per_step")

    eta = (total - step) * sps if (step is not None and total and sps) else None
    return {
        "active": bool(
            step is not None and total and step < total and age is not None and age < STALE_S
        ),
        "video_id": s.get("video_id"),
        "step": step,
        "total": total,
        "percent": s.get("percent") if step is not None else None,
        "seconds_per_step": sps,
        "eta_s": round(eta, 1) if eta is not None else None,
        "age_s": round(age, 1) if age is not None else None,
    }


def _restart_engine() -> None:
    try:
        docker.from_env().containers.get(TARGET).restart(timeout=15)
        print(f"sidecar: restarted '{TARGET}' (hard stop)", flush=True)
    except Exception as exc:
        print(f"sidecar: engine restart FAILED: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server API)
        if self.path == "/restart-engine":
            # Hard stop: the only way to reclaim the GPU from an in-flight
            # denoise (vLLM-Omni aborts don't cancel GPU work). Kills the
            # running render AND wipes the engine's in-memory job records;
            # model reload takes ~3.5 min. Called by the gateway's
            # DELETE /jobs/{id}?hard=true.
            threading.Thread(target=_restart_engine, daemon=True).start()
            body = json.dumps({"restarting": TARGET}).encode()
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            return
        if self.path == "/progress":
            body = json.dumps(_snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):  # keep container logs quiet
        pass


def main() -> None:
    threading.Thread(target=_follow_logs, daemon=True).start()
    print(f"sidecar: serving /progress on :{PORT}, following '{TARGET}'", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
