"""The planner (STORY_029): a skill from data/prompts + a seed image + a count
→ one Gemma call → exactly `count` scripts, plus titles and the arc summary.

Pure library plus one router. Nothing here renders, caches or writes to disk;
a plan is a response. The render chain that consumes plans is STORY_030.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from flow_protocol.media import kind_of
from pydantic import BaseModel, Field

log = logging.getLogger("flow")

COUNT_TOKEN = "{{COUNT}}"
ATTEMPTS = 5
# Measured 2026-09-07: the same 10k-token prompt took 219 s at Ollama's default
# 262k context and 102 s at 32k. The oversized KV cache is slow and eats memory
# the box does not have beside the resident engine.
NUM_CTX = 32768
# STORY_022's rule, applied here too: Gemma must not sit resident (18 GiB)
# after it has answered — a resident Gemma once pushed a render into swap.
KEEP_ALIVE = 0

_SCRIPT = re.compile(r"<<<SCRIPT\s+(\d+)\s*>>>(.*?)<<<END SCRIPT>>>", re.S)
_TITLES = re.compile(r"<<<TITLES>>>(.*?)<<<END TITLES>>>", re.S)
_SUMMARY = re.compile(r"<<<SUMMARY>>>(.*?)<<<END SUMMARY>>>", re.S)


class PlanError(Exception):
    """A plan could not be produced. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


# --- the library --------------------------------------------------------------------


@dataclass(frozen=True)
class Instruction:
    id: str
    name: str
    description: str
    count_locked: bool
    body: str
    path: Path

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "count_locked": self.count_locked}


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """`---` … `---` at the top → (fields, body). Handles `key: value` and the
    folded/indented continuation lines the skills use for `description: >-`."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fields: dict[str, str] = {}
    key = None
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            fields[key] = "" if value in (">-", ">", "|", "|-") else value.strip('"').strip("'")
        elif key is not None:
            fields[key] = (fields[key] + " " + line.strip()).strip()
    body = text[end + 4 :]
    return fields, body.lstrip("\n")


def first_sentence(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    m = re.search(r"[.!?](\s|$)", text)
    out = text[: m.end()].strip() if m else text
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def load_instructions(prompts_dir: Path) -> list[Instruction]:
    """Every *.md in the directory, read fresh each call so a dropped-in skill
    is live on the next request."""
    out: list[Instruction] = []
    if not prompts_dir.is_dir():
        return out
    for path in sorted(prompts_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        fields, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        name = fields.get("name") or path.stem
        out.append(
            Instruction(
                id=name,
                name=name,
                description=first_sentence(fields.get("description", "")),
                count_locked=COUNT_TOKEN not in body,
                body=body,
                path=path,
            )
        )
    return sorted(out, key=lambda i: i.id)


def render_prompt(instruction: Instruction, count: int) -> str:
    return instruction.body.replace(COUNT_TOKEN, str(count))


def parse_plan(text: str, count: int) -> dict[str, Any]:
    """Apply the skill output contract. Strict on the count: rendering one clip
    when six were planned costs an hour and produces nothing usable."""
    blocks = _SCRIPT.findall(text)
    if not blocks:
        body = _TITLES.sub("", _SUMMARY.sub("", text)).strip()
        if count == 1 and body:
            return {"scripts": [body], "titles": _titles(text), "summary": _summary(text)}
        raise PlanError(f"expected {count} scripts, got 0 (no <<<SCRIPT n>>> blocks)")
    if len(blocks) != count:
        raise PlanError(f"expected {count} scripts, got {len(blocks)}")
    numbers = [int(n) for n, _ in blocks]
    if numbers != list(range(1, count + 1)):
        raise PlanError(f"scripts are numbered {numbers}, expected 1..{count} in order")
    scripts = [s.strip() for _, s in blocks]
    if any(not s for s in scripts):
        raise PlanError("a script block is empty")
    return {"scripts": scripts, "titles": _titles(text), "summary": _summary(text)}


def _titles(text: str) -> list[str]:
    m = _TITLES.search(text)
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip()] if m else []


def _summary(text: str) -> str | None:
    m = _SUMMARY.search(text)
    return m.group(1).strip() or None if m else None


class Planner:
    """One Gemma call per attempt, retried immediately on content or transport
    failures (a local model has no rate limit), loud after the last attempt."""

    def __init__(self, url: str, model: str, timeout: float = 600.0, attempts: int = ATTEMPTS) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.attempts = attempts

    def payload(self, instruction: Instruction, count: int, image: bytes) -> dict[str, Any]:
        return {
            "model": self.model,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": NUM_CTX},
            "messages": [
                {"role": "system", "content": render_prompt(instruction, count)},
                {
                    "role": "user",
                    "content": f"The seed image is attached. COUNT = {count}.",
                    "images": [base64.b64encode(image).decode("ascii")],
                },
            ],
        }

    async def plan(self, instruction: Instruction, count: int, image: bytes) -> dict[str, Any]:
        body = self.payload(instruction, count, image)
        reason = "no attempt made"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(1, self.attempts + 1):
                try:
                    resp = await client.post(f"{self.url}/api/chat", json=body)
                except httpx.HTTPError as exc:
                    reason = f"ollama unreachable: {exc}"
                    log.warning("plan attempt %d/%d: %s", attempt, self.attempts, reason)
                    continue
                if resp.status_code >= 400:
                    reason = f"ollama {resp.status_code}: {resp.text[:200]}"
                    log.warning("plan attempt %d/%d: %s", attempt, self.attempts, reason)
                    continue
                content = (resp.json().get("message") or {}).get("content") or ""
                if not content.strip():
                    reason = "empty content"
                    log.warning("plan attempt %d/%d: %s", attempt, self.attempts, reason)
                    continue
                try:
                    parsed = parse_plan(content, count)
                except PlanError as exc:
                    reason = str(exc)
                    log.warning("plan attempt %d/%d: %s", attempt, self.attempts, reason)
                    continue
                return {"instruction": instruction.id, "count": count, **parsed, "attempts": attempt, "model": self.model}
        raise PlanError(f"{reason} (after {self.attempts} attempts)", 502)


# --- the router -----------------------------------------------------------------------


class PlanRequest(BaseModel):
    reference_id: str
    instruction: str
    count: int = Field(1, ge=1)


def build_agent_router(gateway: Any, planner: Planner, prompts_dir: Path) -> APIRouter:
    """`/agent/*` is this backend's own surface, deliberately outside the `/flow`
    protocol prefix so a FLOW_VERSION bump can never collide with it."""
    router = APIRouter(prefix="/agent", tags=["agent"])

    @router.get("/instructions")
    def instructions() -> list[dict[str, Any]]:
        return [i.as_dict() for i in load_instructions(prompts_dir)]

    @router.post("/plan")
    async def plan(req: PlanRequest) -> dict[str, Any]:
        instruction = next((i for i in load_instructions(prompts_dir) if i.id == req.instruction), None)
        if instruction is None:
            raise HTTPException(404, f"unknown instruction {req.instruction!r}")
        if instruction.count_locked and req.count != 1:
            raise HTTPException(422, f"{instruction.id!r} writes a single clip; count must be 1")
        path = gateway.media_path(req.reference_id)
        if path is None:
            raise HTTPException(404, f"unknown reference {req.reference_id!r}")
        if kind_of(path) != "image":
            raise HTTPException(422, "the seed must be an image for now; seeding from a clip arrives with the render chain")
        try:
            return await planner.plan(instruction, req.count, path.read_bytes())
        except PlanError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    return router
