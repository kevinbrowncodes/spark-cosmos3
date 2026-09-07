# Based on kevinbrowncodes/flow @ v0.1.0
#   protocol/python/flow_protocol/examples/cosmos3.py
#   sha256 ea380b93df2a285b75b3b314e01448f6c0e58bfd7a4ec71619dbc988dc86657d
# Deviations from that file (re-diff on every FLOW_VERSION bump):
#   STORY_023  relative imports → absolute `flow_protocol.*` imports
#   STORY_024  `frames` field → `length` (seconds of new video) + frames_for();
#              `count` options [1, 2] → [1]; duration_s from the remembered
#              length / generated_frames, never the payload's unused `seconds`;
#              non-image references refused; footer text; _sizes_by_job →
#              _meta_by_job
#   STORY_025  a finished clip is cached the moment a poll reports done
#              (vLLM-omni forgets jobs on restart), not on first view
#   STORY_026  Extend: a video reference goes as `video=` + condition_seconds,
#              reference_kinds gains "video", and the recycled 73-frame prefix
#              is trimmed off the cached clip (raw kept in flow-outputs-raw/)
"""Reference gateway for spark-cosmos3 (NVIDIA Cosmos 3 Nano behind the
cosmos3-gateway on :8002).

Wire it into gateway/server.py:

    from flow_protocol.router import build_router, mount_ui
    from flow_protocol.examples.cosmos3 import Cosmos3Gateway   # or copy this file

    flow = Cosmos3Gateway(base_url="http://localhost:8002", media_dir=Path("/media"))
    app.include_router(build_router(flow))
    mount_ui(app, "/app/flow-ui")          # the pinned release bundle

Mapping (see spark-cosmos3/docs/api.md and docs/responses.md):
  UI value        cosmos3 form field
  size            size
  length          frames  (seconds of new video → frames_for(), STORY_024)
  steps           steps
  sound           sound
  upsample        upsample
  reasoner        reasoner
  reference       image (multipart file)
  job.status      queued → queued · in_progress → running · completed → done · else failed
  job.progress    merged sidecar/estimate percentage (0–99)
  output bytes    GET /jobs/{id}/content, cached into media_dir/flow-outputs
"""

from __future__ import annotations

import json
import logging
import mimetypes
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from flow_protocol.gateway import FlowGateway, UpstreamError
from flow_protocol.media import MediaStore, kind_of
from flow_protocol.models import Capabilities, GenerateRequest, Job, MediaAsset

DEFAULT_SIZES = ["720x1280", "1280x720", "960x960", "480x832", "832x480"]
FPS = 24
# Seconds of NEW video the user asks for; the same control serves Generate
# (from a still) and Extend (from a clip). Values must satisfy the gateway's
# '2s'..'10s' duration schema after the frame maths below.
LENGTHS = [5, 8, 10]
DEFAULT_LENGTH = 8
# Extend conditions on the source clip's last 3 s (EPIC_001 blind A/B,
# 2026-07-28): gateway condition_window(3.0, 24) → 73 pixel frames.
CONDITION_SECONDS = 3.0
CONDITION_FRAMES = 73
log = logging.getLogger("flow")
STATUS = {"queued": "queued", "in_progress": "running", "completed": "done", "failed": "failed", "cancelled": "failed", "error": "failed"}


def sizes_from_resolution_dict(path: Path, tiers: tuple[str, ...] = ("720", "480")) -> list[str]:
    """`WxH` strings from spark-cosmos3/data/resolution_ratio_dict.json."""
    data = json.loads(Path(path).read_text())
    out: list[str] = []
    for tier in tiers:
        for entry in data.get(tier, {}).values():
            out.append(f"{entry['W']}x{entry['H']}")
    return out or DEFAULT_SIZES


def snap4k1(n: int) -> int:
    """Round up to the next 4k+1: the VAE folds 4 pixel frames into 1 latent."""
    rem = (n - 1) % 4
    return n if rem == 0 else n + (4 - rem)


def frames_for(length_s: float, reference_kind: str) -> int:
    """Total frames to request so that `length_s` seconds of NEW video come back.

    image → snap4k1(L·24)            5→121  8→193  10→241
    video → snap4k1(73 + L·24)       5→193  8→265  10→313  (prefix is recycled source)
    """
    new = round(float(length_s) * FPS)
    return snap4k1(CONDITION_FRAMES + new if reference_kind == "video" else new)


def has_audio(path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    proc = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)], capture_output=True, timeout=60)
    return b"audio" in proc.stdout


def trim_prefix(raw: Path, out: Path, condition_frames: int, fps: int = FPS) -> Path | None:
    """Frame-accurate cut: drop the first `condition_frames` frames of video and
    the matching seconds of audio (STORY_026). Re-encodes — `-ss` with stream
    copy snaps to keyframes. Returns `out`, or None (nothing written) on failure."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.error("ffmpeg not found; cannot trim %s", raw.name)
        return None
    tmp = out.with_suffix(".part")          # .part is not a media suffix, so never listed
    argv = [ffmpeg, "-y", "-loglevel", "error", "-i", str(raw),
            "-vf", f"select='gte(n,{condition_frames})',setpts=PTS-STARTPTS"]
    if has_audio(raw):
        argv += ["-af", f"atrim=start={condition_frames / fps:.7f},asetpts=PTS-STARTPTS", "-c:a", "aac"]
    argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-f", "mp4", str(tmp)]
    proc = subprocess.run(argv, capture_output=True, timeout=900)
    if proc.returncode != 0 or not tmp.is_file():
        log.error("trim failed for %s: %s", raw.name, proc.stderr.decode(errors="replace")[:400])
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out


def _parse_size(size: str | None) -> tuple[int | None, int | None]:
    try:
        w, h = str(size).lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None, None


class Cosmos3Gateway(FlowGateway):
    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        media_dir: Path = Path("/media"),
        sizes: list[str] | None = None,
        resolution_dict: Path | None = None,
        name: str = "Cosmos 3 Nano",
    ) -> None:
        media_dir = Path(media_dir)
        self.store = MediaStore({"in": media_dir / "flow-uploads", "out": media_dir / "flow-outputs"}, upload_root="in")
        self.sizes = sizes or (sizes_from_resolution_dict(resolution_dict) if resolution_dict else DEFAULT_SIZES)
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(60.0, read=600.0))
        self.name = name
        # size + length remembered at submit; the status payload's `size` may
        # be snapped by the engine (720x1280 → 704x1280) and wins when present.
        self._meta_by_job: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> Capabilities:
        default_size = "720x1280" if "720x1280" in self.sizes else self.sizes[0]
        return Capabilities.model_validate(
            {
                "name": self.name,
                "modes": [
                    {
                        "key": "video",
                        "fields": [
                            {"key": "size", "label": "Size", "type": "choice", "role": "size", "options": self.sizes, "default": default_size},
                            {"key": "length", "label": "Length", "type": "choice", "role": "duration",
                             "options": [{"value": n, "label": f"{n} s"} for n in LENGTHS], "default": DEFAULT_LENGTH},
                            {"key": "steps", "label": "Steps", "type": "choice", "options": [35, 50], "default": 35},
                            {"key": "sound", "label": "Sound", "type": "boolean", "default": True},
                            {"key": "upsample", "label": "Upsample prompt", "type": "boolean", "default": True},
                            {"key": "reasoner", "label": "Reasoner", "type": "choice", "options": ["gemma", "opus"], "default": "gemma"},
                            # One at a time: the engine serialises jobs and the UI cannot cancel one.
                            {"key": "count", "label": "Outputs", "type": "choice", "role": "count", "options": [1], "default": 1},
                        ],
                    }
                ],
                "reference": "required",  # the engine dispatches on the media it receives; there is no T2V path
                "reference_kinds": ["image", "video"],  # a video reference = Extend (STORY_026)
                "progress": "percent",
                "strings": {
                    "footer": (
                        f"{self.name} renders one clip at a time — about 45 min at 720p, "
                        "80 min for a 10 s extend. Removing a tile does not stop a render."
                    )
                },
            }
        )

    def generate(self, req: GenerateRequest) -> Job:
        ref = self.store.path(req.reference_id or "")
        if ref is None:
            raise UpstreamError(f"reference {req.reference_id!r} not found", 404)
        kind = kind_of(ref)
        if kind not in ("image", "video"):
            raise UpstreamError("the reference must be an image (generate) or a video (extend)", 422)
        v = req.values
        form = {
            "prompt": req.prompt,
            "size": v["size"],
            "frames": str(frames_for(v["length"], kind)),
            "steps": str(v["steps"]),
            "sound": "true" if v["sound"] else "false",
            "upsample": "true" if v["upsample"] else "false",
            "reasoner": v["reasoner"],
        }
        # The engine dispatches on the media it receives: image → I2V, video →
        # V2V. Extend conditions on the clip's last 3 s (gateway trims the tail).
        if kind == "video":
            form["condition_seconds"] = str(CONDITION_SECONDS)
        fallback = "video/mp4" if kind == "video" else "image/png"
        files = {kind: (ref.name, ref.read_bytes(), mimetypes.guess_type(ref.name)[0] or fallback)}
        try:
            resp = self.client.post("/generate", data=form, files=files)
        except httpx.HTTPError as e:
            raise UpstreamError(f"cosmos3 gateway unreachable: {e}") from e
        if resp.status_code >= 400:
            raise UpstreamError(f"cosmos3 gateway: {resp.text[:400]}", 502 if resp.status_code >= 500 else 422)
        job = resp.json()
        self._meta_by_job[job["id"]] = {
            "size": job.get("size") or v["size"],
            "length": float(v["length"]),
            # V2V only (null on I2V): how many leading frames are recycled source.
            "condition_frames": job.get("condition_frames"),
        }
        return self._to_job(job)

    def job(self, job_id: str) -> Job | None:
        try:
            resp = self.client.get(f"/jobs/{job_id}")
        except httpx.HTTPError as e:
            raise UpstreamError(f"cosmos3 gateway unreachable: {e}") from e
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise UpstreamError(f"cosmos3 gateway: {resp.text[:400]}")
        job = self._to_job(resp.json())
        if job.status == "done":
            self._cache_output(job.id)
        return job

    def _cache_output(self, job_id: str) -> Path | None:
        """Download a finished clip as soon as a poll reports it done (STORY_025).

        The engine forgets every job when it restarts and /jobs/{id}/content
        then 404s, so a clip nobody has clicked yet would be lost. Idempotent:
        an existing cache file is left alone; a failed download leaves nothing
        behind and `media_path` retries lazily on first view.
        """
        target = self.store.roots["out"] / f"{job_id}.mp4"
        if target.is_file():
            return target
        fetched = self._fetch_output(target.name)
        return self._finalise_output(job_id, fetched) if fetched is not None else None

    @property
    def raw_dir(self) -> Path:
        """Untrimmed extend outputs — kept for provenance, never listed (not a store root)."""
        return self.store.roots["out"].parent / "flow-outputs-raw"

    def _finalise_output(self, job_id: str, path: Path) -> Path:
        """Extend outputs: move the raw file aside and serve only the new footage.
        Generate outputs (no condition_frames) are served as they came."""
        condition_frames = self._meta_by_job.get(job_id, {}).get("condition_frames")
        if not condition_frames:
            return path
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        raw = self.raw_dir / path.name
        if raw.exists():
            return path                      # trimmed on an earlier pass
        path.replace(raw)
        if trim_prefix(raw, path, int(condition_frames)) is None:
            raw.replace(path)                # never lose the clip: serve it untrimmed
            log.error("serving %s untrimmed (%d-frame prefix kept)", path.name, condition_frames)
        return path

    def _to_job(self, j: dict[str, Any]) -> Job:
        status = STATUS.get(str(j.get("status")), "failed")
        meta = self._meta_by_job.get(j["id"], {})
        w, h = _parse_size(j.get("size") or meta.get("size"))
        error = j.get("error")
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error)
        # docs/api.md: the payload's `seconds` is an unused default, never the
        # clip length. Prefer what we asked for; fall back to the gateway's
        # generated-frame count (V2V only); otherwise say nothing.
        generated = j.get("generated_frames")
        duration = meta.get("length") if meta.get("length") is not None else (float(generated) / FPS if generated else None)
        return Job(
            id=j["id"],
            status=status,  # type: ignore[arg-type]
            progress=None if j.get("progress") is None else float(j["progress"]),
            media_id=f"out:{j['id']}.mp4" if status == "done" else None,
            width=w,
            height=h,
            duration_s=duration,
            error=str(error) if error else None,
        )

    def list_media(self) -> list[MediaAsset]:
        return self.store.list()

    def media_path(self, media_id: str) -> Path | None:
        p = self.store.path(media_id)
        if p is not None:
            return p
        parts = self.store.split(media_id)
        if parts and parts[0] == "out" and parts[1].endswith(".mp4"):
            return self._cache_output(parts[1][: -len(".mp4")])
        return None

    def _fetch_output(self, filename: str) -> Path | None:
        """First access downloads the finished clip from the gateway's content route."""
        job_id = filename[: -len(".mp4")]
        target = self.store.roots["out"] / filename
        tmp = target.with_suffix(".part")
        try:
            with self.client.stream("GET", f"/jobs/{job_id}/content") as resp:
                if resp.status_code >= 400:
                    return None
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            tmp.replace(target)
        except httpx.HTTPError:
            tmp.unlink(missing_ok=True)
            return None
        return target

    def upload(self, filename: str, data: bytes, content_type: str | None) -> MediaAsset:
        return self.store.save_upload(filename, data)
