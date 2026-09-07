"""One implementation behind two prefixes (STORY_032).

`/agent/*` is this backend's own surface; `/flow/agent/*` is the protocol's
mirror of it (flow v0.2.0, PROTOCOL.md §Agent mode). Both go through
`AgentBridge`, which owns every rule — 404/409/422 — so the CLI and the UI can
never disagree. The gateway object implements `FlowAgent` by delegating here,
and declares `capabilities.agent` only once the bridge is attached.

The `FlowAgent` import is guarded: a sidecar image pinned to a flow release
without Agent mode still builds and runs, simply without the mirror.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flow_protocol.gateway import UpstreamError
from flow_protocol.media import kind_of

from flow.agent import Instruction, PlanError, Planner, load_instructions

try:  # flow-protocol ≥ 0.2.0
    from flow_protocol.gateway import FlowAgent
    from flow_protocol.models import Instruction as InstructionModel, Plan, PlanRequest, Run, RunRequest

    HAS_AGENT_PROTOCOL = True
except ImportError:  # pragma: no cover — exercised by the image build against older pins
    FlowAgent = object  # type: ignore[assignment,misc]
    HAS_AGENT_PROTOCOL = False

AGENT_CAPABILITIES: dict[str, Any] = {
    "instructions": True,
    "count": {"min": 1, "max": 12, "default": 3},
    "confirm": "always",
    "fields": ["size", "length", "steps", "sound", "upsample", "reasoner"],
}


class AgentBridge:
    """The rules, once. Raises UpstreamError(message, status); callers map it."""

    def __init__(self, gateway: Any, planner: Planner, executor: Any, prompts_dir: Path) -> None:
        self.gateway = gateway
        self.planner = planner
        self.executor = executor
        self.prompts_dir = Path(prompts_dir)

    # --- lookups ---------------------------------------------------------------

    def instruction(self, instruction_id: str, count: int) -> Instruction:
        instruction = next((i for i in load_instructions(self.prompts_dir) if i.id == instruction_id), None)
        if instruction is None:
            raise UpstreamError(f"unknown instruction {instruction_id!r}", 404)
        if instruction.count_locked and count != 1:
            raise UpstreamError(f"{instruction.id!r} writes a single clip; count must be 1", 422)
        return instruction

    def run_or_404(self, run_id: str) -> dict[str, Any]:
        run = self.executor.store.load(run_id)
        if run is None:
            raise UpstreamError(f"unknown run {run_id!r}", 404)
        return run

    def script_index(self, run: dict[str, Any], n: int) -> int:
        if not 1 <= n <= run["count"]:
            raise UpstreamError(f"run has {run['count']} scripts; no script {n}", 404)
        if run["state"] != "review":
            raise UpstreamError(f"scripts can only change while the run is in review (it is {run['state']})", 409)
        return n - 1

    # --- operations (dict in, dict out — the protocol layer converts) -----------

    def instructions(self) -> list[dict[str, Any]]:
        return [i.as_dict() for i in load_instructions(self.prompts_dir)]

    async def plan(self, reference_id: str, instruction_id: str, count: int) -> dict[str, Any]:
        instruction = self.instruction(instruction_id, count)
        path = self.gateway.media_path(reference_id)
        if path is None:
            raise UpstreamError(f"unknown reference {reference_id!r}", 404)
        if kind_of(path) != "image":
            raise UpstreamError("the seed must be an image for a dry plan; a run accepts a video seed", 422)
        try:
            return await self.planner.plan(instruction, count, path.read_bytes())
        except PlanError as exc:
            raise UpstreamError(str(exc), exc.status) from exc

    def create_run(self, reference_id: str, instruction_id: str, count: int, values: dict[str, Any] | None, project_id: str | None, autostart: bool) -> dict[str, Any]:
        instruction = self.instruction(instruction_id, count)
        if self.gateway.media_path(reference_id) is None:
            raise UpstreamError(f"unknown reference {reference_id!r}", 404)
        try:
            return self.executor.create(reference_id, instruction, count, values, project_id, autostart)
        except ValueError as exc:
            raise UpstreamError(str(exc), 422) from exc

    def list_runs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self.executor.store.list(project_id)

    def run(self, run_id: str) -> dict[str, Any] | None:
        return self.executor.store.load(run_id)

    def edit_script(self, run_id: str, n: int, text: str) -> dict[str, Any]:
        run = self.run_or_404(run_id)
        i = self.script_index(run, n)
        text = text.strip()
        if not text:
            raise UpstreamError("text must not be empty", 422)
        run["scripts"][i] = text
        run["clips"][i]["script"] = text
        return self.executor.store.save(run)

    async def rewrite_script(self, run_id: str, n: int) -> dict[str, Any]:
        run = self.run_or_404(run_id)
        self.script_index(run, n)
        try:
            return await self.executor.rewrite(run, n)
        except PlanError as exc:
            raise UpstreamError(str(exc), exc.status) from exc

    def approve(self, run_id: str) -> dict[str, Any]:
        run = self.run_or_404(run_id)
        if run["state"] != "review":
            raise UpstreamError(f"only a run in review can be approved (it is {run['state']})", 409)
        return self.executor.approve(run)

    def resume(self, run_id: str) -> dict[str, Any]:
        run = self.run_or_404(run_id)
        if run["state"] not in ("failed", "paused"):
            raise UpstreamError(f"only a failed or paused run can be resumed (it is {run['state']})", 409)
        return self.executor.resume(run)


class ProtocolAgent(FlowAgent):  # type: ignore[misc]
    """`FlowAgent` for `build_router`: pydantic in, pydantic out, the bridge in between."""

    def __init__(self, bridge: AgentBridge) -> None:
        self.bridge = bridge

    def instructions(self) -> list[InstructionModel]:
        return [InstructionModel.model_validate(i) for i in self.bridge.instructions()]

    async def plan(self, req: PlanRequest) -> Plan:
        return Plan.model_validate(await self.bridge.plan(req.reference_id, req.instruction, req.count))

    def create_run(self, req: RunRequest) -> Run:
        return Run.model_validate(self.bridge.create_run(req.reference_id, req.instruction, req.count, req.values, req.project_id, req.autostart))

    def list_runs(self, project_id: str | None = None) -> list[Run]:
        return [Run.model_validate(r) for r in self.bridge.list_runs(project_id)]

    def run(self, run_id: str) -> Run | None:
        r = self.bridge.run(run_id)
        return Run.model_validate(r) if r is not None else None

    def edit_script(self, run_id: str, n: int, text: str) -> Run:
        return Run.model_validate(self.bridge.edit_script(run_id, n, text))

    async def rewrite_script(self, run_id: str, n: int) -> Run:
        return Run.model_validate(await self.bridge.rewrite_script(run_id, n))

    def approve(self, run_id: str) -> Run:
        return Run.model_validate(self.bridge.approve(run_id))

    def resume(self, run_id: str) -> Run:
        return Run.model_validate(self.bridge.resume(run_id))
