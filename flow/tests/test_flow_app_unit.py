"""Unit tests for flow/app.py — environment parsing and the app factory (STORY_023)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import shutil
import subprocess

import pytest

from flow.app import DEFAULTS, UI_PATHS, UUID_SHIM, build_app, build_gateway, inject_shim, settings


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


INDEX = '<!doctype html><html><head><meta charset="utf-8"><title>flow</title><script type="module" src="./assets/index-abc.js"></script></head><body></body></html>'


def make_ui(tmp_path: Path) -> Path:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text(INDEX)
    (ui / "assets" / "index-abc.js").write_text("console.log('bundle')")
    return ui


def test_build_app_with_ui_and_resolution_dict(tmp_path):
    ui = make_ui(tmp_path)
    rrd = tmp_path / "rrd.json"
    rrd.write_text(json.dumps({"720": {"9,16": {"W": 720, "H": 1280}}, "480": {"16,9": {"W": 832, "H": 480}}}))
    app = build_app({"FLOW_MEDIA_DIR": str(tmp_path / "m"), "RESOLUTION_DICT": str(rrd), "FLOW_UI_DIR": str(ui)})
    with TestClient(app) as c:
        assert c.get("/ui/").status_code == 200 and "flow" in c.get("/ui/").text
        sizes = [o["value"] for o in c.get("/flow/capabilities").json()["modes"][0]["fields"][0]["options"]]
    assert sizes == ["720x1280", "832x480"]


# --- STORY_027 / BUG_005 --------------------------------------------------------------------

def test_inject_shim_goes_first_in_head_exactly_once():
    out = inject_shim(INDEX)
    assert out.startswith('<!doctype html><html><head>' + UUID_SHIM + '<meta')
    assert inject_shim(out) == out and out.count("randomUUID") == UUID_SHIM.count("randomUUID")
    assert inject_shim("<p>no head</p>") == UUID_SHIM + "<p>no head</p>"


@pytest.mark.skipif(not shutil.which("node"), reason="node is needed to execute the shim")
def test_shim_produces_v4_uuids_without_native_randomuuid():
    js = UUID_SHIM[len("<script>"):-len("</script>")]
    probe = (
        "const wc = require('crypto').webcrypto;"
        "globalThis.crypto = { getRandomValues: (b) => wc.getRandomValues(b) };"   # insecure-context shape
        + js +
        "const re = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;"
        "const ids = new Set(Array.from({length: 200}, () => globalThis.crypto.randomUUID()));"
        "if (ids.size !== 200 || ![...ids].every((u) => re.test(u))) { console.log('BAD', [...ids][0]); process.exit(1); }"
        "console.log('OK', [...ids][0]);"
    )
    proc = subprocess.run(["node", "-e", probe], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node is needed to execute the shim")
def test_shim_leaves_a_native_randomuuid_alone():
    js = UUID_SHIM[len("<script>"):-len("</script>")]
    probe = "globalThis.crypto = { randomUUID: () => 'native' };" + js + "process.exit(globalThis.crypto.randomUUID() === 'native' ? 0 : 1);"
    assert subprocess.run(["node", "-e", probe], capture_output=True, timeout=30).returncode == 0


def test_ui_is_served_at_both_paths_with_the_shim_and_untouched_assets(tmp_path):
    app = build_app({"FLOW_MEDIA_DIR": str(tmp_path / "m"), "RESOLUTION_DICT": str(tmp_path / "none.json"), "FLOW_UI_DIR": str(make_ui(tmp_path))})
    with TestClient(app) as c:
        for path in UI_PATHS:
            page = c.get(f"{path}/")
            assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
            assert UUID_SHIM in page.text and "./assets/index-abc.js" in page.text
            asset = c.get(f"{path}/assets/index-abc.js")
            assert asset.status_code == 200 and asset.text == "console.log('bundle')"
            assert c.get(f"{path}/index.html").status_code == 200          # static copy still reachable
        assert c.get("/flow/capabilities").json()["protocol"] == 1           # API wins under /flow/*
        assert c.get("/flow/jobs/does-not-exist", headers={"accept": "application/json"}).status_code in (404, 502)
        root = c.get("/", follow_redirects=False)
        assert root.status_code in (302, 307) and root.headers["location"] == "/flow/"
        assert c.get("/flow/nope.js").status_code == 404

