"""ASGI entrypoint for the Flow sidecar (STORY_023).

Configuration is environment-only so the same image runs unchanged on every
Spark. Exposed as a uvicorn *factory* (`uvicorn flow.app:build_app --factory`):
constructing the gateway creates the media directories, which must not happen
as an import side effect — tests and tooling import this module too.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from flow_protocol.router import create_app

from flow.gateway import Cosmos3Gateway

log = logging.getLogger("flow")

DEFAULTS: dict[str, str] = {
    # Compose service name, not localhost: the sidecar runs in its own container.
    "COSMOS_GATEWAY_URL": "http://gateway:8002",
    "FLOW_MEDIA_DIR": "/media",
    "RESOLUTION_DICT": "/data/resolution_ratio_dict.json",
    "FLOW_UI_DIR": "/app/flow-ui",
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


def build_app(env: Mapping[str, str] | None = None) -> FastAPI:
    cfg = settings(env)
    ui = Path(cfg["FLOW_UI_DIR"])
    if not ui.is_dir():
        log.warning("UI bundle %s not found; serving the protocol only", ui)
    return create_app(build_gateway(cfg), ui_dir=ui if ui.is_dir() else None)
