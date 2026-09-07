"""STORY_030 integration: create → plan → review → approve → chain → done, with
the cosmos3 gateway and Ollama both faked. The executor is driven by tick()."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from flow_protocol.conformance import tiny_png

from flow.app import build_app

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"
GW = "http://fake-gateway:8002"
OLLAMA = "http://fake-ollama:11434"
PLAN3 = "<<<SCRIPT 1>>>one<<<END SCRIPT>>><<<SCRIPT 2>>>two<<<END SCRIPT>>><<<SCRIPT 3>>>three<<<END SCRIPT>>><<<TITLES>>>🔥 Dusk Run\n💪 B<<<END TITLES>>><<<SUMMARY>>>| a |<<<END SUMMARY>>>"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def ollama_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "done": True})


@pytest.fixture
def env(tmp_path):
    prompts = tmp_path / "prompts"
    shutil.copytree(FIXTURES, prompts)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 41943040 kB\n")      # 40 GiB: gate passes
    return {
        "FLOW_MEDIA_DIR": str(tmp_path / "media"), "RESOLUTION_DICT": str(tmp_path / "none.json"), "FLOW_UI_DIR": str(tmp_path / "no-ui"),
        "COSMOS_GATEWAY_URL": GW, "GEMMA_URL": OLLAMA, "GEMMA_MODEL": "gemma4:26b", "PROMPTS_DIR": str(prompts),
        "AGENT_MIN_FREE_GIB": "30", "AGENT_TICK_S": "0",
    }, meminfo


@pytest.fixture
def app(env):
    cfg, meminfo = env
    a = build_app(cfg)
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


def tick(app) -> str | None:
    return asyncio.run(app.state.executor.tick())


def upload(client, name="seed.png", data=None, ctype="image/png") -> str:
    r = client.post("/flow/uploads", files={"file": (name, data or tiny_png(), ctype)})
    assert r.status_code == 201
    return r.json()["id"]


def job(status: str, jid: str, **extra) -> httpx.Response:
    return httpx.Response(200, json={"id": jid, "status": status, "size": "832x480", **extra})


# --- create + validation -------------------------------------------------------------------

def test_create_run_defaults_and_validation(client, mocks):
    rid = upload(client)
    r = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 3, "project_id": "p1"})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["state"] == "planning" and run["step"] == "Writing 3 scripts…" and run["title"] == "Untitled run"
    assert run["values"]["size"] == "832x480" and run["values"]["length"] == 10 and run["values"]["count"] == 1
    assert run["seed_kind"] == "image" and len(run["clips"]) == 3 and run["clip_count"] == 3
    assert client.get(f"/agent/runs/{run['id']}").json()["id"] == run["id"]
    assert [x["id"] for x in client.get("/agent/runs", params={"project_id": "p1"}).json()] == [run["id"]]
    assert client.get("/agent/runs", params={"project_id": "other"}).json() == []
    assert client.get("/agent/runs/run_nope").status_code == 404

    assert client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 3, "values": {"size": "999x999"}}).status_code == 422
    assert client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 3, "values": {"bogus": 1}}).status_code == 422
    assert client.post("/agent/runs", json={"reference_id": rid, "instruction": "single-skill", "count": 2}).status_code == 422
    assert client.post("/agent/runs", json={"reference_id": rid, "instruction": "nope", "count": 1}).status_code == 404
    assert client.post("/agent/runs", json={"reference_id": "in:missing.png", "instruction": "scene-skill", "count": 1}).status_code == 404


# --- the full chain --------------------------------------------------------------------------

def test_plan_review_approve_and_render_three_clips(client, app, mocks, env):
    cfg, meminfo = env
    rid = upload(client)
    run_id = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 3}).json()["id"]

    # planning → review
    ollama = mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply(PLAN3))
    assert "planned 3 scripts → review" in tick(app)
    run = client.get(f"/agent/runs/{run_id}").json()
    assert run["state"] == "review" and run["scripts"] == ["one", "two", "three"] and run["title"] == "🔥 Dusk Run"
    assert [c["script"] for c in run["clips"]] == ["one", "two", "three"] and run["summary"] == "| a |"
    assert tick(app) is None                                    # review waits for a human

    # review: edit, rewrite, guards
    assert client.patch(f"/agent/runs/{run_id}/scripts/2", json={"text": "  two, slower  "}).json()["scripts"][1] == "two, slower"
    assert client.patch(f"/agent/runs/{run_id}/scripts/9", json={"text": "x"}).status_code == 404
    assert client.patch(f"/agent/runs/{run_id}/scripts/1", json={"text": ""}).status_code == 422
    ollama.mock(return_value=ollama_reply("<<<SCRIPT 3>>>three, rewritten<<<END SCRIPT>>>"))
    r = client.post(f"/agent/runs/{run_id}/scripts/3/rewrite")
    assert r.status_code == 200 and r.json()["scripts"] == ["one", "two, slower", "three, rewritten"]
    sent = json.loads(ollama.calls.last.request.content)
    user = sent["messages"][1]["content"]
    assert "ONLY script 3 of 3" in user and "<<<SCRIPT 2>>>\ntwo, slower" in user and sent["messages"][1]["images"]
    assert client.post(f"/agent/runs/{run_id}/resume").status_code == 409

    # approve → queued; a second approve is a 409
    assert client.post(f"/agent/runs/{run_id}/approve").json()["state"] == "queued"
    assert client.post(f"/agent/runs/{run_id}/approve").status_code == 409
    assert client.patch(f"/agent/runs/{run_id}/scripts/1", json={"text": "late"}).status_code == 409

    # memory gate: below threshold → paused with the exact message, then passes
    meminfo.write_text("MemAvailable: 23068672 kB\n")           # 22 GiB
    assert "Paused: 22 GiB available, need 30" in tick(app)
    assert client.get(f"/agent/runs/{run_id}").json()["state"] == "paused"
    meminfo.write_text("MemAvailable: 41943040 kB\n")

    # clip 1: image seed
    gen = mocks.post(f"{GW}/generate").mock(return_value=job("queued", "j1"))
    assert "submitted clip 1 as j1" in tick(app)
    assert b'name="image"' in gen.calls.last.request.content and b"condition_seconds" not in gen.calls.last.request.content
    run = client.get(f"/agent/runs/{run_id}").json()
    assert run["state"] == "rendering" and run["step"] == "Rendering clip 1 of 3" and run["clips"][0]["job_id"] == "j1"

    poll = mocks.get(f"{GW}/jobs/j1").mock(return_value=job("in_progress", "j1", progress=40))
    assert "in_progress" in tick(app) or "running" in tick(app)
    assert client.get(f"/agent/runs/{run_id}").json()["clips"][0]["progress"] == 40

    poll.mock(return_value=job("completed", "j1"))
    mocks.get(f"{GW}/jobs/j1/content").mock(return_value=httpx.Response(200, content=MP4))
    assert "clip 1 done → queued" in tick(app)
    run = client.get(f"/agent/runs/{run_id}").json()
    assert run["clips"][0]["media_id"] == "out:j1.mp4" and run["clip_index"] == 1 and run["step"] == "Caching clip 1"

    # clip 2: extends clip 1's cached file
    gen.mock(return_value=job("queued", "j2", condition_frames=None))
    assert "submitted clip 2 as j2" in tick(app)
    body = gen.calls.last.request.content
    assert b'name="video"' in body and b'name="condition_seconds"' in body and b"\r\n3.0\r\n" in body and b"two, slower" in body
    mocks.get(f"{GW}/jobs/j2").mock(return_value=job("completed", "j2"))
    mocks.get(f"{GW}/jobs/j2/content").mock(return_value=httpx.Response(200, content=MP4))
    assert "clip 2 done → queued" in tick(app)

    # clip 3 → done
    gen.mock(return_value=job("queued", "j3"))
    assert "submitted clip 3 as j3" in tick(app)
    mocks.get(f"{GW}/jobs/j3").mock(return_value=job("completed", "j3"))
    mocks.get(f"{GW}/jobs/j3/content").mock(return_value=httpx.Response(200, content=MP4))
    assert "clip 3 done → done" in tick(app)
    run = client.get(f"/agent/runs/{run_id}").json()
    assert run["state"] == "done" and run["step"] == "Done" and [c["media_id"] for c in run["clips"]] == ["out:j1.mp4", "out:j2.mp4", "out:j3.mp4"]
    outputs = {a["id"] for a in client.get("/flow/media").json() if a["source"] == "output"}
    assert outputs == {"out:j1.mp4", "out:j2.mp4", "out:j3.mp4"}
    assert tick(app) is None


# --- failures, resume, restart -----------------------------------------------------------------

def test_autostart_failures_resume_and_restart(client, app, mocks, env):
    cfg, meminfo = env
    rid = upload(client)
    run_id = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 1, "autostart": True}).json()["id"]
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 1>>>solo<<<END SCRIPT>>>"))
    assert "→ queued" in tick(app)                                   # autostart skips review

    gen = mocks.post(f"{GW}/generate").mock(return_value=job("queued", "j9"))
    assert "submitted clip 1 as j9" in tick(app)
    mocks.get(f"{GW}/jobs/j9").mock(return_value=httpx.Response(404, json={"detail": "gone"}))
    assert "engine probably restarted" in tick(app)
    run = client.get(f"/agent/runs/{run_id}").json()
    assert run["state"] == "failed" and run["step"].startswith("Failed at clip 1")
    assert client.post(f"/agent/runs/{run_id}/approve").status_code == 409

    # resume → queued at the same clip, job cleared; a transient 5xx while polling is not fatal
    assert client.post(f"/agent/runs/{run_id}/resume").json()["state"] == "queued"
    gen.mock(return_value=job("queued", "j10"))
    assert "submitted clip 1 as j10" in tick(app)
    mocks.get(f"{GW}/jobs/j10").mock(return_value=httpx.Response(503, text="engine loading"))
    assert "will retry" in tick(app)
    assert client.get(f"/agent/runs/{run_id}").json()["state"] == "rendering"

    # restart: a new app over the same media dir picks the rendering run up where it was
    app2 = build_app(cfg)
    app2.state.executor.meminfo = meminfo
    mocks.get(f"{GW}/jobs/j10").mock(return_value=job("failed", "j10", error={"message": "cuda oom"}))
    assert "clip 1 failed" in tick(app2)
    with TestClient(app2) as c2:
        run = c2.get(f"/agent/runs/{run_id}").json()
        assert run["state"] == "failed" and "cuda oom" in run["step"]
        assert c2.post(f"/agent/runs/{run_id}/resume").json()["state"] == "queued"

    # submit rejected by the gateway → failed with its reason
    gen.mock(return_value=httpx.Response(400, text="frames must be 4k+1"))
    assert "submit failed" in tick(app2)
    assert "frames must be 4k+1" in client.get(f"/agent/runs/{run_id}").json()["error"]


def test_planning_failures(client, app, mocks, env):
    cfg, _ = env
    rid = upload(client)
    run_id = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 3}).json()["id"]
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 1>>>only<<<END SCRIPT>>>"))
    assert "planning failed" in tick(app)
    run = client.get(f"/agent/runs/{run_id}").json()
    assert run["state"] == "failed" and "expected 3 scripts, got 1" in run["error"]

    # a rewrite that keeps failing surfaces its reason, not a 500
    r2 = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 1}).json()["id"]
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 1>>>x<<<END SCRIPT>>>"))
    tick(app)
    mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 7>>>wrong<<<END SCRIPT>>>"))
    r = client.post(f"/agent/runs/{r2}/scripts/1/rewrite")
    assert r.status_code == 502 and "exactly one <<<SCRIPT 1>>>" in r.json()["detail"]

    # the seed or the skill vanishing between create and plan is a failed run, not a crash
    r3 = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 1}).json()["id"]
    Path(cfg["PROMPTS_DIR"], "scene-skill.md").unlink()
    assert "no longer in the library" in tick(app)
    assert client.get(f"/agent/runs/{r3}").json()["state"] == "failed"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required to make the clip")
def test_video_seed_plans_from_its_poster_and_extends_it(client, app, mocks, tmp_path):
    clip = tmp_path / "seed.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=64x64:d=1:r=24", "-pix_fmt", "yuv420p", str(clip)], check=True)
    rid = upload(client, "seed.mp4", clip.read_bytes(), "video/mp4")
    run_id = client.post("/agent/runs", json={"reference_id": rid, "instruction": "scene-skill", "count": 1, "autostart": True}).json()["id"]
    assert client.get(f"/agent/runs/{run_id}").json()["seed_kind"] == "video"
    ollama = mocks.post(f"{OLLAMA}/api/chat").mock(return_value=ollama_reply("<<<SCRIPT 1>>>go<<<END SCRIPT>>>"))
    assert "→ queued" in tick(app)
    assert json.loads(ollama.calls.last.request.content)["messages"][1]["images"][0].startswith("/9j/")   # a JPEG poster, not the mp4
    gen = mocks.post(f"{GW}/generate").mock(return_value=job("queued", "jv"))
    assert "submitted clip 1 as jv" in tick(app)
    assert b'name="video"' in gen.calls.last.request.content and b'name="condition_seconds"' in gen.calls.last.request.content


def test_lifespan_starts_and_stops_the_loop(env, monkeypatch):
    cfg, _ = env
    app = build_app({**cfg, "AGENT_TICK_S": "0.01"})
    calls = []

    async def fake_tick():
        calls.append(1)

    monkeypatch.setattr(app.state.executor, "tick", fake_tick)
    with TestClient(app):
        import time
        time.sleep(0.1)
    assert calls, "the background loop should have ticked at least once"
