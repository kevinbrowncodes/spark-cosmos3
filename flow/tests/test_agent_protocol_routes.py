"""STORY_032: the protocol's /flow/agent/* mirror shares the bridge with /agent/*."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from flow_protocol.conformance import run_checks, tiny_png

from flow.agent_bridge import HAS_AGENT_PROTOCOL
from flow.app import build_app

# The Docker test stage builds against the pinned flow release; before the tag
# that ships Agent mode (STORY_028/032) the mirror simply does not exist.
pytestmark = pytest.mark.skipif(not HAS_AGENT_PROTOCOL, reason="pinned flow-protocol predates Agent mode")

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"
GW = "http://fake-gateway:8002"
OLLAMA = "http://fake-ollama:11434"
PLAN2 = "<<<SCRIPT 1>>>one<<<END SCRIPT>>><<<SCRIPT 2>>>two<<<END SCRIPT>>><<<TITLES>>>🎬 Two<<<END TITLES>>>"


def ollama_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "done": True})


@pytest.fixture
def app(tmp_path):
    prompts = tmp_path / "prompts"
    shutil.copytree(FIXTURES, prompts)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 41943040 kB\n")
    a = build_app({
        "FLOW_MEDIA_DIR": str(tmp_path / "media"), "RESOLUTION_DICT": str(tmp_path / "none.json"), "FLOW_UI_DIR": str(tmp_path / "no-ui"),
        "COSMOS_GATEWAY_URL": GW, "GEMMA_URL": OLLAMA, "GEMMA_MODEL": "gemma4:26b", "PROMPTS_DIR": str(prompts), "AGENT_TICK_S": "0",
    })
    a.state.executor.meminfo = meminfo
    return a


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mocks():
    with respx.mock(assert_all_called=False) as m:
        yield m


def tick(app):
    return asyncio.run(app.state.executor.tick())


def upload(client) -> str:
    r = client.post("/flow/uploads", files={"file": ("seed.png", tiny_png(), "image/png")})
    return r.json()["id"]


def test_capabilities_declare_agent_and_both_prefixes_agree(client):
    caps = client.get("/flow/capabilities").json()
    assert caps["agent"] == {"instructions": True, "count": {"min": 1, "max": 12, "default": 3}, "confirm": "always", "fields": ["size", "length", "steps", "sound", "upsample", "reasoner"]}
    assert client.get("/flow/agent/instructions").json() == client.get("/agent/instructions").json()
    assert client.get("/flow/agent/runs").json() == [] == client.get("/agent/runs").json()


def test_protocol_plan_validation(client, mocks):
    rid = upload(client)
    assert client.post("/flow/agent/plan", json={"reference_id": rid, "instruction": "nope", "count": 1}).status_code == 404
    assert client.post("/flow/agent/plan", json={"reference_id": rid, "instruction": "single-skill", "count": 2}).status_code == 422
    assert client.post("/flow/agent/plan", json={"reference_id": "in:missing.png", "instruction": "scene-skill", "count": 1}).status_code == 404
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply(PLAN2))
    p = client.post("/flow/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 2}).json()
    assert p["scripts"] == ["one", "two"] and p["titles"] == ["🎬 Two"] and p["model"] == "gemma4:26b"
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 1>>>x<<<END SCRIPT>>>"))
    r = client.post("/flow/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 2})
    assert r.status_code == 502 and "expected 2 scripts" in r.json()["detail"]


def test_protocol_run_lifecycle_shares_the_bridge(client, app, mocks):
    rid = upload(client)
    r = client.post("/flow/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 2, "project_id": "ui"})
    assert r.status_code == 202, r.text
    run = r.json()
    rid_run = run["id"]
    assert run["state"] == "planning" and run["clip_count"] == 2 and run["values"]["size"] == "832x480"
    # the same run is visible under both prefixes
    assert client.get(f"/agent/runs/{rid_run}").json()["id"] == rid_run
    assert client.get("/flow/agent/runs", params={"project_id": "ui"}).json()[0]["id"] == rid_run

    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply(PLAN2))
    tick(app)
    run = client.get(f"/flow/agent/runs/{rid_run}").json()
    assert run["state"] == "review" and run["scripts"] == ["one", "two"] and run["title"] == "🎬 Two"

    assert client.patch(f"/flow/agent/runs/{rid_run}/scripts/2", json={"text": " two, edited "}).json()["scripts"][1] == "two, edited"
    assert client.patch(f"/flow/agent/runs/{rid_run}/scripts/9", json={"text": "x"}).status_code == 404
    assert client.patch(f"/flow/agent/runs/{rid_run}/scripts/1", json={"text": ""}).status_code == 422
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 1>>>one, rewritten<<<END SCRIPT>>>"))
    assert client.post(f"/flow/agent/runs/{rid_run}/scripts/1/rewrite").json()["scripts"][0] == "one, rewritten"
    assert client.post(f"/flow/agent/runs/{rid_run}/resume").status_code == 409
    assert client.post(f"/flow/agent/runs/{rid_run}/approve").json()["state"] == "queued"
    assert client.post(f"/flow/agent/runs/{rid_run}/approve").status_code == 409
    assert client.post(f"/agent/runs/{rid_run}/approve").status_code == 409          # same rule, other prefix
    assert client.patch(f"/flow/agent/runs/{rid_run}/scripts/1", json={"text": "late"}).status_code == 409

    gen = mocks.post(f"{GW}/generate").mock(return_value=httpx.Response(200, json={"id": "j1", "status": "queued", "size": "832x480"}))
    tick(app)
    assert client.get(f"/flow/agent/runs/{rid_run}").json()["state"] == "rendering" and b'name="image"' in gen.calls.last.request.content
    mocks.get(f"{GW}/jobs/j1").mock(return_value=httpx.Response(404, json={"detail": "gone"}))
    tick(app)
    run = client.get(f"/flow/agent/runs/{rid_run}").json()
    assert run["state"] == "failed" and run["step"].startswith("Failed at clip 1")
    assert client.post(f"/flow/agent/runs/{rid_run}/resume").json()["state"] == "queued"
    assert client.get("/flow/agent/runs/run_nope").status_code == 404
    assert client.post("/flow/agent/runs/run_nope/approve").status_code == 404
    assert client.post("/flow/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 1, "values": {"bogus": 1}}).status_code == 422


def test_conformance_with_agent_declared(client, mocks):
    mocks.get(f"{GW}/jobs/does-not-exist").mock(return_value=httpx.Response(404, json={"detail": "no such job"}))
    checks = run_checks(client, generate=False)
    agent = [c for c in checks if c.name.startswith("agent:")]
    assert agent, "agent checks must run when capabilities.agent is declared"
    failed = [(c.name, c.detail) for c in checks if not c.ok]
    assert not failed, failed
