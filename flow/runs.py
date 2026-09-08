"""Runs and the executor (STORY_030): a plan becomes a durable record, and a
single tick-driven executor renders it clip by clip through the sidecar's own
gateway client — the same path a UI click takes.

Nothing here talks to the engine directly; every clip is `Cosmos3Gateway.generate`
followed by `Cosmos3Gateway.job`, so caching and prefix trimming come for free
and the agent can never diverge from a manual generate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from flow_protocol import GenerateRequest, normalise_request, size_for_seed
from flow_protocol.gateway import UpstreamError
from flow_protocol.media import kind_of

from flow.agent import Instruction, PlanError, Planner, load_instructions

log = logging.getLogger("flow")

STATES = ("planning", "review", "queued", "rendering", "done", "failed", "paused")
# Extend conditions on the previous clip's last 3 s (EPIC_001 blind A/B, 2026-07-28).
CONDITION_SECONDS = 3.0
# EPIC_003: a 6-clip scene is ~2.5 h at 480p and ~7.6 h at 720p, so the agent asks for the
# cheaper tier by default. Only the *pixel budget* of this size is used — the shape comes from
# the seed (STORY_033), so the orientation written here is irrelevant.
DEFAULT_TIER = "832x480"
DEFAULT_VALUES: dict[str, Any] = {"length": 10, "steps": 35, "sound": True, "upsample": True, "reasoner": "gemma"}
# The size-from-seed rule itself lives upstream (flow_protocol.sizing, STORY-608 / STORY_034) so the
# Flow UI can preview the same choice; this sidecar keeps the measuring (ffprobe, for video seeds
# too) and the policy of what tier to spend by default.


def probe_dimensions(path: Path | str) -> tuple[int, int] | None:
    """Width and height of an image or a video, or None if it cannot be read."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        log.error("ffprobe not found; cannot measure %s", path)
        return None
    argv = [ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)]
    try:
        out = subprocess.run(argv, capture_output=True, timeout=60).stdout.decode(errors="replace")
        w, h = (int(n) for n in out.strip().splitlines()[0].split(",")[:2])
        return (w, h) if w > 0 and h > 0 else None
    except (subprocess.SubprocessError, ValueError, IndexError) as exc:
        log.warning("could not measure %s: %s", path, exc)
        return None


def size_options(caps: Any, mode: str = "video") -> list[str]:
    """The size strings the gateway offers, or [] if it does not say."""
    spec = caps.mode(mode) if hasattr(caps, "mode") else None
    field = spec.field("size") if spec else None
    return [str(o.value) for o in (field.options or [])] if field else []


def new_run_id() -> str:
    return "run_" + secrets.token_hex(6)


def mem_available_gib(meminfo: Path | str = "/proc/meminfo") -> float | None:
    """Host memory, even from inside a container — /proc/meminfo is not namespaced."""
    try:
        for line in Path(meminfo).read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except OSError:
        return None
    return None


def step_label(run: dict[str, Any]) -> str:
    n, total = run.get("clip_index", 0), run.get("count", 0)
    state = run["state"]
    if state == "planning":
        return f"Writing {total} script{'s' if total != 1 else ''}…"
    if state == "review":
        return "Waiting for review"
    if state == "queued":
        return f"Queued clip {n + 1} of {total}"          # never "Caching": the cache is written before the run is queued (BUG_009)
    if state == "rendering":
        return f"Rendering clip {n + 1} of {total}"
    if state == "paused":
        return f"Paused: {run.get('error') or 'gate'}"
    if state == "failed":
        return f"Failed at clip {n + 1}: {run.get('error') or 'unknown'}"
    return "Done"


class RunStore:
    """One JSON file per run, written atomically. Survives restarts by construction."""

    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, run_id: str) -> Path:
        return self.dir / f"{run_id}.json"

    def save(self, run: dict[str, Any]) -> dict[str, Any]:
        run["updated_at"] = time.time()
        run["step"] = step_label(run)
        tmp = self.path(run["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(run, indent=2))
        tmp.replace(self.path(run["id"]))
        return run

    def load(self, run_id: str) -> dict[str, Any] | None:
        p = self.path(run_id)
        return json.loads(p.read_text()) if p.is_file() else None

    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        runs = [json.loads(p.read_text()) for p in self.dir.glob("run_*.json")]
        if project_id is not None:
            runs = [r for r in runs if r.get("project_id") == project_id]
        return sorted(runs, key=lambda r: r.get("created_at", 0), reverse=True)


class Executor:
    """One unit of work per `tick()`: plan a run, submit the next clip of the
    active run, or poll it. A background loop calls it; tests call it directly."""

    def __init__(
        self,
        gateway: Any,
        planner: Planner,
        store: RunStore,
        prompts_dir: Path,
        min_free_gib: float = 30.0,
        meminfo: Path | str = "/proc/meminfo",
    ) -> None:
        self.gateway = gateway
        self.planner = planner
        self.store = store
        self.prompts_dir = Path(prompts_dir)
        self.min_free_gib = min_free_gib
        self.meminfo = meminfo

    # --- creation ---------------------------------------------------------------------

    def create(
        self,
        reference_id: str,
        instruction: Instruction,
        count: int,
        values: dict[str, Any] | None,
        project_id: str | None,
        autostart: bool,
    ) -> dict[str, Any]:
        seed = self.gateway.media_path(reference_id)
        if seed is None:
            raise ValueError(f"unknown reference {reference_id!r}")
        kind = kind_of(seed)
        if kind not in ("image", "video"):
            raise ValueError("the seed must be an image or a video")
        caps = self.gateway.capabilities()
        merged = {**DEFAULT_VALUES, **(values or {}), "count": 1}
        # Shape from the seed, resolution from whatever was asked for (STORY_033 / BUG_012).
        # A size the gateway does not offer is left alone so it still fails validation below,
        # rather than being quietly turned into a valid one.
        options, requested = size_options(caps), merged.get("size")
        if requested is None or requested in options:
            chosen = size_for_seed(options, requested or DEFAULT_TIER, probe_dimensions(seed))
            if chosen:
                merged["size"] = chosen
        req = normalise_request(caps, GenerateRequest(mode="video", prompt="plan", values=merged, reference_id=reference_id))
        run = {
            "id": new_run_id(),
            "project_id": project_id,
            "title": "Untitled run",
            "state": "planning",
            "clip_index": 0,
            "clip_count": count,
            "instruction": instruction.id,
            "count": count,
            "values": req.values,
            "reference_id": reference_id,
            "seed_kind": kind,
            "scripts": [],
            "titles": [],
            "summary": None,
            "clips": [{"n": i + 1, "script": None, "job_id": None, "media_id": None, "status": "pending", "progress": None, "error": None} for i in range(count)],
            "autostart": autostart,
            "error": None,
            "attempts": 0,
            "created_at": time.time(),
        }
        return self.store.save(run)

    # --- the tick ---------------------------------------------------------------------------

    async def tick(self) -> str | None:
        runs = self.store.list()
        rendering = [r for r in runs if r["state"] == "rendering"]
        if rendering:
            return await self._poll(rendering[-1])
        planning = [r for r in runs if r["state"] == "planning"]
        if planning:
            return await self._plan(planning[-1])
        ready = [r for r in runs if r["state"] in ("queued", "paused")]
        if ready:
            return await self._submit(ready[-1])       # oldest first: list() is newest-first
        return None

    async def run_forever(self, interval_s: float) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 — the loop must outlive any one run's failure
                log.exception("executor tick failed")
            await asyncio.sleep(interval_s)

    # --- planning ---------------------------------------------------------------------------

    def _seed_image(self, run: dict[str, Any]) -> bytes:
        path = self.gateway.thumbnail_path(run["reference_id"]) if run["seed_kind"] == "video" else self.gateway.media_path(run["reference_id"])
        if path is None:
            raise PlanError(f"seed {run['reference_id']!r} is no longer available", 404)
        return Path(path).read_bytes()

    def _instruction(self, run: dict[str, Any]) -> Instruction:
        instruction = next((i for i in load_instructions(self.prompts_dir) if i.id == run["instruction"]), None)
        if instruction is None:
            raise PlanError(f"instruction {run['instruction']!r} is no longer in the library", 404)
        return instruction

    async def _plan(self, run: dict[str, Any]) -> str:
        try:
            plan = await self.planner.plan(self._instruction(run), run["count"], self._seed_image(run))
        except PlanError as exc:
            run.update(state="failed", error=str(exc))
            self.store.save(run)
            return f"{run['id']}: planning failed: {exc}"
        run.update(scripts=plan["scripts"], titles=plan["titles"], summary=plan["summary"], attempts=plan["attempts"])
        run["title"] = plan["titles"][0] if plan["titles"] else "Untitled run"
        for clip, script in zip(run["clips"], plan["scripts"]):
            clip["script"] = script
        run["state"] = "queued" if run["autostart"] else "review"
        self.store.save(run)
        return f"{run['id']}: planned {len(plan['scripts'])} scripts → {run['state']}"

    async def rewrite(self, run: dict[str, Any], n: int) -> dict[str, Any]:
        text = await self.planner.rewrite(self._instruction(run), run["count"], self._seed_image(run), run["scripts"], n)
        run["scripts"][n - 1] = text
        run["clips"][n - 1]["script"] = text
        return self.store.save(run)

    # --- rendering ----------------------------------------------------------------------------

    def _gate(self, run: dict[str, Any]) -> bool:
        free = mem_available_gib(self.meminfo)
        if free is not None and free < self.min_free_gib:
            run.update(state="paused", error=f"{free:.0f} GiB available, need {self.min_free_gib:.0f}")
            self.store.save(run)
            return False
        return True

    async def _submit(self, run: dict[str, Any]) -> str:
        if not self._gate(run):
            return f"{run['id']}: {run['step']}"
        n = run["clip_index"]
        clip = run["clips"][n]
        reference = run["reference_id"] if n == 0 else run["clips"][n - 1]["media_id"]
        req = GenerateRequest(mode="video", prompt=clip["script"], values=run["values"], reference_id=reference)
        try:
            job = await asyncio.to_thread(self.gateway.generate, req)
        except UpstreamError as exc:
            run.update(state="failed", error=str(exc))
            clip.update(status="failed", error=str(exc))
            self.store.save(run)
            return f"{run['id']}: submit failed: {exc}"
        clip.update(job_id=job.id, status=job.status, progress=job.progress, error=None)
        run.update(state="rendering", error=None)
        self.store.save(run)
        return f"{run['id']}: submitted clip {n + 1} as {job.id}"

    async def _poll(self, run: dict[str, Any]) -> str:
        n = run["clip_index"]
        clip = run["clips"][n]
        try:
            job = await asyncio.to_thread(self.gateway.job, clip["job_id"])
        except UpstreamError as exc:
            return f"{run['id']}: poll error, will retry: {exc}"   # transient 5xx: keep rendering
        if job is None:
            reason = f"job {clip['job_id']} is gone — the engine probably restarted"
            run.update(state="failed", error=reason)
            clip.update(status="failed", error=reason)
            self.store.save(run)
            return f"{run['id']}: {reason}"
        clip.update(status=job.status, progress=job.progress)
        if job.status == "failed":
            run.update(state="failed", error=job.error or "render failed")
            clip["error"] = job.error
            self.store.save(run)
            return f"{run['id']}: clip {n + 1} failed"
        if job.status == "done":
            clip.update(media_id=job.media_id, progress=100)
            run["clip_index"] = n + 1
            run["state"] = "done" if run["clip_index"] >= run["count"] else "queued"
            self.store.save(run)
            return f"{run['id']}: clip {n + 1} done → {run['state']}"
        self.store.save(run)
        return f"{run['id']}: clip {n + 1} {job.status} {job.progress}"

    # --- review transitions --------------------------------------------------------------------

    def approve(self, run: dict[str, Any]) -> dict[str, Any]:
        run.update(state="queued", error=None)
        return self.store.save(run)

    def resume(self, run: dict[str, Any]) -> dict[str, Any]:
        clip = run["clips"][run["clip_index"]]
        clip.update(status="pending", job_id=None, progress=None, error=None)
        run.update(state="queued", error=None)
        return self.store.save(run)
