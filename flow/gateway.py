# Copied verbatim from kevinbrowncodes/flow @ v0.1.0
#   protocol/python/flow_protocol/examples/cosmos3.py
#   sha256 ea380b93df2a285b75b3b314e01448f6c0e58bfd7a4ec71619dbc988dc86657d
# The ONLY edits are the three relative imports, rewritten as absolute
# `flow_protocol.*` imports so the file works outside that package (STORY_023).
# Corrections against docs/api.md belong to STORY_024 — do not make them here.
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
  frames          frames
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
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from flow_protocol.gateway import FlowGateway, UpstreamError
from flow_protocol.media import MediaStore
from flow_protocol.models import Capabilities, GenerateRequest, Job, MediaAsset

DEFAULT_SIZES = ["720x1280", "1280x720", "960x960", "480x832", "832x480"]
STATUS = {"queued": "queued", "in_progress": "running", "completed": "done", "failed": "failed", "cancelled": "failed", "error": "failed"}


def sizes_from_resolution_dict(path: Path, tiers: tuple[str, ...] = ("720", "480")) -> list[str]:
    """`WxH` strings from spark-cosmos3/data/resolution_ratio_dict.json."""
    data = json.loads(Path(path).read_text())
    out: list[str] = []
    for tier in tiers:
        for entry in data.get(tier, {}).values():
            out.append(f"{entry['W']}x{entry['H']}")
    return out or DEFAULT_SIZES


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
        self._sizes_by_job: dict[str, str] = {}

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
                            {"key": "frames", "label": "Frames", "type": "choice", "options": [121, 189, 237, 300], "default": 189},
                            {"key": "steps", "label": "Steps", "type": "choice", "options": [35, 50], "default": 35},
                            {"key": "sound", "label": "Sound", "type": "boolean", "default": True},
                            {"key": "upsample", "label": "Upsample prompt", "type": "boolean", "default": True},
                            {"key": "reasoner", "label": "Reasoner", "type": "choice", "options": ["gemma", "opus"], "default": "gemma"},
                            {"key": "count", "label": "Outputs", "type": "choice", "role": "count", "options": [1, 2], "default": 1},
                        ],
                    }
                ],
                "reference": "required",  # the engine dispatches on the media it receives; there is no T2V path
                "reference_kinds": ["image"],
                "progress": "percent",
                "strings": {"footer": f"{self.name} can make mistakes, so double check it"},
            }
        )

    def generate(self, req: GenerateRequest) -> Job:
        image = self.store.path(req.reference_id or "")
        if image is None:
            raise UpstreamError(f"reference {req.reference_id!r} not found", 404)
        v = req.values
        form = {
            "prompt": req.prompt,
            "size": v["size"],
            "frames": str(v["frames"]),
            "steps": str(v["steps"]),
            "sound": "true" if v["sound"] else "false",
            "upsample": "true" if v["upsample"] else "false",
            "reasoner": v["reasoner"],
        }
        files = {"image": (image.name, image.read_bytes(), mimetypes.guess_type(image.name)[0] or "image/png")}
        try:
            resp = self.client.post("/generate", data=form, files=files)
        except httpx.HTTPError as e:
            raise UpstreamError(f"cosmos3 gateway unreachable: {e}") from e
        if resp.status_code >= 400:
            raise UpstreamError(f"cosmos3 gateway: {resp.text[:400]}", 502 if resp.status_code >= 500 else 422)
        job = resp.json()
        self._sizes_by_job[job["id"]] = job.get("size") or v["size"]
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
        return self._to_job(resp.json())

    def _to_job(self, j: dict[str, Any]) -> Job:
        status = STATUS.get(str(j.get("status")), "failed")
        w, h = _parse_size(j.get("size") or self._sizes_by_job.get(j["id"]))
        error = j.get("error")
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error)
        seconds = j.get("seconds")
        return Job(
            id=j["id"],
            status=status,  # type: ignore[arg-type]
            progress=None if j.get("progress") is None else float(j["progress"]),
            media_id=f"out:{j['id']}.mp4" if status == "done" else None,
            width=w,
            height=h,
            duration_s=float(seconds) if seconds not in (None, "") else None,
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
            return self._fetch_output(parts[1])
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
