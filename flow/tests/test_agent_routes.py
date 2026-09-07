"""STORY_029 integration tests: /agent/instructions and /agent/plan with Ollama faked."""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from flow_protocol.conformance import tiny_png

from flow.app import build_app

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"
OLLAMA = "http://fake-ollama:11434"
GOOD = "<<<SCRIPT 1>>>a<<<END SCRIPT>>><<<SCRIPT 2>>>b<<<END SCRIPT>>><<<SCRIPT 3>>>c<<<END SCRIPT>>><<<TITLES>>>🔥 T<<<END TITLES>>><<<SUMMARY>>>S<<<END SUMMARY>>>"
ONE = "<<<SCRIPT 1>>>only<<<END SCRIPT>>>"


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"model": "gemma4:26b", "message": {"role": "assistant", "content": content}, "done": True})


@pytest.fixture
def prompts(tmp_path):
    d = tmp_path / "prompts"
    shutil.copytree(FIXTURES, d)
    return d


@pytest.fixture
def client(tmp_path, prompts):
    app = build_app({
        "FLOW_MEDIA_DIR": str(tmp_path / "media"), "RESOLUTION_DICT": str(tmp_path / "none.json"),
        "FLOW_UI_DIR": str(tmp_path / "no-ui"), "GEMMA_URL": OLLAMA, "GEMMA_MODEL": "gemma4:26b", "PROMPTS_DIR": str(prompts),
    })
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ollama():
    with respx.mock(base_url=OLLAMA, assert_all_called=False) as m:
        yield m


def upload(client, name="seed.png", data=None, ctype="image/png") -> str:
    r = client.post("/flow/uploads", files={"file": (name, data or tiny_png(), ctype)})
    assert r.status_code == 201
    return r.json()["id"]


# --- instructions -----------------------------------------------------------------------------

def test_instructions_list_and_hot_reload(client, prompts):
    rows = client.get("/agent/instructions").json()
    assert [r["id"] for r in rows] == ["bare", "scene-skill", "single-skill"]
    assert {r["id"]: r["count_locked"] for r in rows} == {"bare": False, "scene-skill": False, "single-skill": True}
    assert set(rows[1]) == {"id", "name", "description", "count_locked"}
    (prompts / "new-skill.md").write_text("---\nname: new-skill\ndescription: Fresh.\n---\n{{COUNT}}\n")
    assert "new-skill" in [r["id"] for r in client.get("/agent/instructions").json()]   # no restart needed


# --- plan --------------------------------------------------------------------------------------

def test_plan_happy_path_and_payload(client, ollama):
    seed = tiny_png()
    rid = upload(client, data=seed)
    route = ollama.post("/api/chat").mock(return_value=reply(GOOD))
    r = client.post("/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scripts"] == ["a", "b", "c"] and body["titles"] == ["🔥 T"] and body["summary"] == "S"
    assert body["attempts"] == 1 and body["model"] == "gemma4:26b" and body["instruction"] == "scene-skill" and body["count"] == 3
    sent = json.loads(route.calls.last.request.content)
    assert sent["options"] == {"num_ctx": 32768} and sent["keep_alive"] == 0 and sent["stream"] is False
    system, user = sent["messages"]
    assert "exactly 3 scripts" in system["content"] and "{{COUNT}}" not in system["content"]
    assert user["images"] == [base64.b64encode(seed).decode()] and "COUNT = 3" in user["content"]


def test_plan_retries_on_wrong_count_then_succeeds(client, ollama):
    rid = upload(client)
    route = ollama.post("/api/chat").mock(side_effect=[reply(ONE), reply(""), reply(GOOD)])
    r = client.post("/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 3})
    assert r.status_code == 200 and r.json()["attempts"] == 3 and route.call_count == 3


def test_plan_gives_up_after_five_attempts(client, ollama):
    rid = upload(client)
    route = ollama.post("/api/chat").mock(return_value=reply(ONE))
    r = client.post("/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 3})
    assert r.status_code == 502 and "expected 3 scripts, got 1" in r.json()["detail"] and "after 5 attempts" in r.json()["detail"]
    assert route.call_count == 5


def test_plan_transport_failures_are_502(client, ollama):
    rid = upload(client)
    ollama.post("/api/chat").mock(side_effect=httpx.ConnectError("down"))
    r = client.post("/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 1})
    assert r.status_code == 502 and "unreachable" in r.json()["detail"]
    ollama.post("/api/chat").mock(return_value=httpx.Response(500, text="model load failed"))
    r = client.post("/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 1})
    assert r.status_code == 502 and "ollama 500" in r.json()["detail"]


def test_plan_single_clip_skill_accepts_markerless_reply(client, ollama):
    rid = upload(client)
    ollama.post("/api/chat").mock(return_value=reply("One paragraph of motion."))
    r = client.post("/agent/plan", json={"reference_id": rid, "instruction": "single-skill"})   # count defaults to 1
    assert r.status_code == 200 and r.json()["scripts"] == ["One paragraph of motion."]


def test_plan_validation(client, ollama, tmp_path):
    rid = upload(client)
    assert client.post("/agent/plan", json={"reference_id": rid, "instruction": "single-skill", "count": 2}).status_code == 422
    assert client.post("/agent/plan", json={"reference_id": rid, "instruction": "nope", "count": 1}).status_code == 404
    assert client.post("/agent/plan", json={"reference_id": "in:missing.png", "instruction": "scene-skill", "count": 1}).status_code == 404
    assert client.post("/agent/plan", json={"reference_id": rid, "instruction": "scene-skill", "count": 0}).status_code == 422
    clip = upload(client, "clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32, "video/mp4")
    r = client.post("/agent/plan", json={"reference_id": clip, "instruction": "scene-skill", "count": 1})
    assert r.status_code == 422 and "must be an image" in r.json()["detail"]
