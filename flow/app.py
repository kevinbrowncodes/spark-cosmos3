"""ASGI entrypoint for the Flow sidecar (STORY_023).

Configuration is environment-only so the same image runs unchanged on every
Spark. Exposed as a uvicorn *factory* (`uvicorn flow.app:build_app --factory`):
constructing the gateway creates the media directories, which must not happen
as an import side effect — tests and tooling import this module too.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from flow_protocol.router import build_router

from flow.agent import Planner, build_agent_router
from flow.agent_bridge import HAS_AGENT_PROTOCOL, AgentBridge, ProtocolAgent
from flow.gateway import Cosmos3Gateway
from flow.runs import Executor, RunStore

log = logging.getLogger("flow")

# Where the UI is served: /flow is the address people use (STORY_027), /ui is
# the upstream convention. The API lives under /flow/* and is registered first,
# so its paths always win over the static mount.
UI_PATHS = ("/flow", "/ui")

# BUG_005: browsers expose crypto.randomUUID only in secure contexts (https or
# localhost) and flow v0.1.0 calls it unguarded (contract.js:266). The LAN uses
# plain http, so the served index page gets a polyfill built on
# getRandomValues, which insecure contexts do have. Injected in memory at
# serve time — the pinned bundle on disk is untouched, and this becomes a
# no-op the moment upstream guards the call.
UUID_SHIM = (
    "<script>(function(){var c=globalThis.crypto;if(c&&typeof c.randomUUID===\"function\")return;"
    "if(!c){c={};globalThis.crypto=c;}c.randomUUID=function(){var b=new Uint8Array(16);"
    "if(typeof c.getRandomValues===\"function\"){c.getRandomValues(b);}else{for(var i=0;i<16;i++){b[i]=Math.random()*256|0;}}"
    "b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;var h=\"\";for(var j=0;j<16;j++){h+=(b[j]<16?\"0\":\"\")+b[j].toString(16);}"
    "return h.slice(0,8)+\"-\"+h.slice(8,12)+\"-\"+h.slice(12,16)+\"-\"+h.slice(16,20)+\"-\"+h.slice(20);};})();</script>"
)

DEFAULTS: dict[str, str] = {
    # Compose service name, not localhost: the sidecar runs in its own container.
    "COSMOS_GATEWAY_URL": "http://gateway:8002",
    "FLOW_MEDIA_DIR": "/media",
    "RESOLUTION_DICT": "/data/resolution_ratio_dict.json",
    "FLOW_UI_DIR": "/app/flow-ui",
    # The agent's planner (STORY_029): the same Ollama/Gemma the gateway upsamples with.
    "GEMMA_URL": "http://host.docker.internal:11434",
    "GEMMA_MODEL": "gemma4:26b",
    "PROMPTS_DIR": "/data/prompts",
    # The executor (STORY_030): memory gate before every clip, tick interval (0 = no background loop).
    "AGENT_MIN_FREE_GIB": "30",
    "AGENT_TICK_S": "5",
}


def settings(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolved configuration. An unset *or empty* variable takes the default,
    so `FLOW_MEDIA_DIR=` in .env behaves like an absent line."""
    source = os.environ if env is None else env
    return {key: source.get(key) or default for key, default in DEFAULTS.items()}


def build_gateway(cfg: Mapping[str, str]) -> Cosmos3Gateway:
    rrd = Path(cfg["RESOLUTION_DICT"])
    if not rrd.is_file():
        log.warning("resolution dict %s not found; using the built-in size list", rrd)
    return Cosmos3Gateway(
        base_url=cfg["COSMOS_GATEWAY_URL"],
        media_dir=Path(cfg["FLOW_MEDIA_DIR"]),
        resolution_dict=rrd if rrd.is_file() else None,
    )


def inject_shim(html: str) -> str:
    """The shim goes first in <head>, ahead of the bundle's module script."""
    if UUID_SHIM in html:
        return html
    return html.replace("<head>", "<head>" + UUID_SHIM, 1) if "<head>" in html else UUID_SHIM + html


def build_app(env: Mapping[str, str] | None = None) -> FastAPI:
    cfg = settings(env)
    gateway = build_gateway(cfg)
    planner = Planner(cfg["GEMMA_URL"], cfg["GEMMA_MODEL"])
    executor = Executor(
        gateway, planner, RunStore(Path(cfg["FLOW_MEDIA_DIR"]) / "flow-runs"), Path(cfg["PROMPTS_DIR"]),
        min_free_gib=float(cfg["AGENT_MIN_FREE_GIB"]),
    )
    tick_s = float(cfg["AGENT_TICK_S"])

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # One executor loop per process. Runs on disk survive restarts by construction;
        # the first ticks pick up whatever state they were left in.
        task = asyncio.create_task(executor.run_forever(tick_s)) if tick_s > 0 else None
        try:
            yield
        finally:
            if task:
                task.cancel()

    # STORY_032: one bridge behind /agent/* and, when flow-protocol knows Agent mode,
    # the protocol's /flow/agent/* mirror. Attach before build_router reads capabilities.
    bridge = AgentBridge(gateway, planner, executor, Path(cfg["PROMPTS_DIR"]))
    if HAS_AGENT_PROTOCOL:
        gateway.agent = ProtocolAgent(bridge)
    else:
        log.warning("flow-protocol without Agent mode: /flow/agent/* not mounted (bump FLOW_VERSION)")

    app = FastAPI(title=f"{gateway.capabilities().name} — Flow gateway", lifespan=lifespan)
    app.state.executor = executor
    app.state.bridge = bridge
    app.include_router(build_router(gateway))
    app.include_router(build_agent_router(bridge))

    ui = Path(cfg["FLOW_UI_DIR"])
    index = ui / "index.html"
    if not index.is_file():
        log.warning("UI bundle %s not found; serving the protocol only", ui)
        return app

    page = inject_shim(index.read_text())

    def serve_index() -> HTMLResponse:
        return HTMLResponse(page)

    app.add_api_route("/", lambda: RedirectResponse(UI_PATHS[0] + "/"), methods=["GET"], include_in_schema=False)
    for path in UI_PATHS:
        # The shimmed index must be registered before the mount that would
        # otherwise serve the raw index.html for the same URL.
        app.add_api_route(f"{path}/", serve_index, methods=["GET"], include_in_schema=False)
        app.mount(path, StaticFiles(directory=str(ui), html=True), name=f"flow-ui{path.replace('/', '-')}")
    return app
