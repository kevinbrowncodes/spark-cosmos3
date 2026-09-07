"""Integration tests: every /flow route through the real router with the
cosmos3 gateway on :8002 faked by respx (STORY_023)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from flow_protocol.conformance import run_checks, tiny_png
from flow_protocol.router import create_app

from flow.gateway import Cosmos3Gateway

GW = "http://fake-gateway:8002"
VALUES = {"size": "720x1280", "length": 8, "steps": 35, "sound": True, "upsample": True, "reasoner": "gemma", "count": 1}


@pytest.fixture
def media(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(media: Path):
    app = create_app(Cosmos3Gateway(base_url=GW, media_dir=media))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def upstream():
    with respx.mock(base_url=GW, assert_all_called=False) as mock:
        yield mock


def upload(client: TestClient, name: str = "still.png", data: bytes | None = None, ctype: str = "image/png") -> str:
    resp = client.post("/flow/uploads", files={"file": (name, data or tiny_png(), ctype)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- capabilities / media -----------------------------------------------------

def test_capabilities(client):
    body = client.get("/flow/capabilities").json()
    assert body["protocol"] == 1 and body["name"] == "Cosmos 3 Nano" and body["modes"][0]["key"] == "video"


def test_upload_list_full_thumbnail(client):
    rid = upload(client)
    assert rid.startswith("in:")
    listing = client.get("/flow/media").json()
    assert [a["id"] for a in listing] == [rid] and listing[0]["kind"] == "image" and listing[0]["source"] == "upload"
    assert client.get(f"/flow/media/{rid}", params={"type": "FULL"}).headers["content-type"] == "image/png"
    assert client.get(f"/flow/media/{rid}", params={"type": "THUMBNAIL"}).headers["content-type"].startswith("image/")


def test_empty_upload_is_422(client):
    assert client.post("/flow/uploads", files={"file": ("e.png", b"", "image/png")}).status_code == 422


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required for video posters")
def test_video_upload_gets_an_image_poster(client, tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1:r=24", "-pix_fmt", "yuv420p", str(clip)], check=True)
    rid = upload(client, "clip.mp4", clip.read_bytes(), "video/mp4")
    assert client.get(f"/flow/media/{rid}", params={"type": "FULL"}).headers["content-type"] == "video/mp4"
    thumb = client.get(f"/flow/media/{rid}", params={"type": "THUMBNAIL"})
    assert thumb.status_code == 200 and thumb.headers["content-type"].startswith("image/")


@pytest.mark.parametrize("bad", ["nope:x.mp4", "out:x.txt", "in:../etc/passwd", "no-separator"])
def test_unknown_media_ids_are_404(client, bad):
    assert client.get(f"/flow/media/{bad}", params={"type": "FULL"}).status_code == 404


# --- generate ------------------------------------------------------------------

def test_generate_forwards_the_form_and_maps_the_job(client, upstream):
    rid = upload(client)
    route = upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_1", "status": "queued", "size": "704x1280"}))
    resp = client.post("/flow/generate", json={"mode": "video", "prompt": "a calm lake", "values": VALUES, "reference_id": rid})
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["id"] == "video_gen_1" and job["status"] == "queued" and (job["width"], job["height"]) == (704, 1280)
    sent = route.calls.last.request.content
    for field in (b'name="image"', b'name="prompt"', b'name="size"', b'name="frames"', b'name="steps"', b'name="sound"', b'name="upsample"', b'name="reasoner"'):
        assert field in sent
    assert b"a calm lake" in sent and b"\r\n193\r\n" in sent and b"\r\ntrue\r\n" in sent   # length 8 → 193 frames
    assert job["duration_s"] == 8


def test_generate_defaults_send_the_default_length(client, upstream):
    rid = upload(client)
    route = upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_2", "status": "queued"}))
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "reference_id": rid}).status_code == 202
    assert b"\r\n193\r\n" in route.calls.last.request.content


@pytest.mark.parametrize("values", [{**VALUES, "length": 12}, {**VALUES, "count": 2}, {**VALUES, "frames": 189}])
def test_generate_rejects_values_the_ui_cannot_offer(client, values):
    rid = upload(client)
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": values, "reference_id": rid}).status_code == 422


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required to make the clip")
def test_generate_refuses_a_video_reference_for_now(client, tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1:r=24", "-pix_fmt", "yuv420p", str(clip)], check=True)
    rid = upload(client, "clip.mp4", clip.read_bytes(), "video/mp4")
    resp = client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid})
    assert resp.status_code == 422 and "must be an image" in resp.json()["detail"]


def test_generate_gateway_4xx_becomes_422_with_its_detail(client, upstream):
    rid = upload(client)
    upstream.post("/generate").mock(return_value=httpx.Response(400, text="steps must be 35 or 50"))
    resp = client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid})
    assert resp.status_code == 422 and "steps must be 35 or 50" in resp.json()["detail"]


def test_generate_gateway_5xx_becomes_502(client, upstream):
    rid = upload(client)
    upstream.post("/generate").mock(return_value=httpx.Response(503, text="engine loading"))
    resp = client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid})
    assert resp.status_code == 502 and "engine loading" in resp.json()["detail"]


def test_generate_unreachable_gateway_becomes_502(client, upstream):
    rid = upload(client)
    upstream.post("/generate").mock(side_effect=httpx.ConnectError("boom"))
    resp = client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid})
    assert resp.status_code == 502 and "unreachable" in resp.json()["detail"]


def test_generate_validation_errors(client):
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": "in:missing.png"}).status_code == 404
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES}).status_code == 422
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": {"__bogus__": 1}}).status_code == 422
    assert client.post("/flow/generate", json={"mode": "not-a-mode", "prompt": "x"}).status_code == 422


# --- jobs ------------------------------------------------------------------------

def test_job_running(client, upstream):
    upstream.get("/jobs/video_gen_1").mock(return_value=httpx.Response(200, json={"id": "video_gen_1", "status": "in_progress", "progress": 42, "size": "704x1280", "seconds": "4"}))
    job = client.get("/flow/jobs/video_gen_1").json()
    assert job["status"] == "running" and job["progress"] == 42 and job["media_id"] is None
    assert job["duration_s"] is None   # `seconds` is an unused default (docs/api.md), not a length


def test_job_done_carries_media_id(client, upstream):
    upstream.get("/jobs/video_gen_1").mock(return_value=httpx.Response(200, json={"id": "video_gen_1", "status": "completed", "progress": 100, "size": "704x1280"}))
    job = client.get("/flow/jobs/video_gen_1").json()
    assert job["status"] == "done" and job["media_id"] == "out:video_gen_1.mp4"


def test_job_failed_surfaces_the_error_message(client, upstream):
    upstream.get("/jobs/video_gen_1").mock(return_value=httpx.Response(200, json={"id": "video_gen_1", "status": "failed", "error": {"message": "cuda oom"}}))
    job = client.get("/flow/jobs/video_gen_1").json()
    assert job["status"] == "failed" and job["error"] == "cuda oom"


def test_job_upstream_statuses(client, upstream):
    upstream.get("/jobs/gone").mock(return_value=httpx.Response(404, json={"detail": "no such job"}))
    assert client.get("/flow/jobs/gone").status_code == 404
    upstream.get("/jobs/broken").mock(return_value=httpx.Response(500, text="boom"))
    assert client.get("/flow/jobs/broken").status_code == 502
    upstream.get("/jobs/down").mock(side_effect=httpx.ConnectError("down"))
    assert client.get("/flow/jobs/down").status_code == 502


# --- outputs -----------------------------------------------------------------------

MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def test_output_is_fetched_once_and_cached(client, upstream, media):
    route = upstream.get("/jobs/video_gen_1/content").mock(return_value=httpx.Response(200, content=MP4_BYTES, headers={"content-type": "video/mp4"}))
    first = client.get("/flow/media/out:video_gen_1.mp4", params={"type": "FULL"})
    assert first.status_code == 200 and first.content == MP4_BYTES
    assert (media / "flow-outputs" / "video_gen_1.mp4").read_bytes() == MP4_BYTES
    assert client.get("/flow/media/out:video_gen_1.mp4", params={"type": "FULL"}).status_code == 200
    assert route.call_count == 1
    assert client.get("/flow/media").json()[0]["source"] == "output"


def test_output_upstream_404_is_404_and_leaves_no_partial(client, upstream, media):
    upstream.get("/jobs/nope/content").mock(return_value=httpx.Response(404))
    assert client.get("/flow/media/out:nope.mp4", params={"type": "FULL"}).status_code == 404
    assert not list((media / "flow-outputs").iterdir())


def test_output_transport_error_is_404_and_leaves_no_partial(client, upstream, media):
    upstream.get("/jobs/flaky/content").mock(side_effect=httpx.ReadError("reset"))
    assert client.get("/flow/media/out:flaky.mp4", params={"type": "FULL"}).status_code == 404
    assert not list((media / "flow-outputs").iterdir())


# --- the protocol's own conformance suite, in-process ---------------------------------

def test_conformance_contract_checks_pass_in_process(client, upstream):
    # The suite probes an unknown job; the real gateway proxies the engine's 404.
    upstream.get("/jobs/does-not-exist").mock(return_value=httpx.Response(404, json={"detail": "no such job"}))
    failed = [c for c in run_checks(client, generate=False) if not c.ok]
    assert not failed, [(c.name, c.detail) for c in failed]
