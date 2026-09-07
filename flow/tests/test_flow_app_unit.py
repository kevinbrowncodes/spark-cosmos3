"""Unit tests for flow/app.py — environment parsing and the app factory (STORY_023)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from flow.app import DEFAULTS, build_app, build_gateway, settings


def test_settings_defaults_when_nothing_is_set():
    assert settings({}) == DEFAULTS


def test_settings_override_and_empty_string_falls_back():
    cfg = settings({"COSMOS_GATEWAY_URL": "http://box:1", "FLOW_MEDIA_DIR": ""})
    assert cfg["COSMOS_GATEWAY_URL"] == "http://box:1"
    assert cfg["FLOW_MEDIA_DIR"] == DEFAULTS["FLOW_MEDIA_DIR"]


def test_settings_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("FLOW_UI_DIR", "/nowhere")
    assert settings()["FLOW_UI_DIR"] == "/nowhere"


def test_build_gateway_without_resolution_dict_uses_builtin_sizes(tmp_path):
    gw = build_gateway({**DEFAULTS, "FLOW_MEDIA_DIR": str(tmp_path / "m"), "RESOLUTION_DICT": str(tmp_path / "missing.json")})
    assert "720x1280" in gw.sizes and (tmp_path / "m" / "flow-uploads").is_dir()


def test_build_app_without_ui_serves_the_protocol_only(tmp_path):
    app = build_app({"FLOW_MEDIA_DIR": str(tmp_path / "m"), "RESOLUTION_DICT": str(tmp_path / "none.json"), "FLOW_UI_DIR": str(tmp_path / "no-ui")})
    # Behavioural, not structural: FastAPI versions differ in how an included
    # router shows up in app.routes (this bit the Docker test stage).
    with TestClient(app) as c:
        assert c.get("/flow/capabilities").status_code == 200
        assert c.get("/ui/").status_code == 404


def test_build_app_with_ui_and_resolution_dict(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>flow</title>")
    rrd = tmp_path / "rrd.json"
    rrd.write_text(json.dumps({"720": {"9,16": {"W": 720, "H": 1280}}, "480": {"16,9": {"W": 832, "H": 480}}}))
    app = build_app({"FLOW_MEDIA_DIR": str(tmp_path / "m"), "RESOLUTION_DICT": str(rrd), "FLOW_UI_DIR": str(ui)})
    with TestClient(app) as c:
        assert c.get("/ui/").status_code == 200 and "flow" in c.get("/ui/").text
        sizes = [o["value"] for o in c.get("/flow/capabilities").json()["modes"][0]["fields"][0]["options"]]
    assert sizes == ["720x1280", "832x480"]
