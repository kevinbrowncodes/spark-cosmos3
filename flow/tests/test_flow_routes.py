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
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def make_clip(path: Path, seconds: float = 4.0, audio: bool = True) -> Path:
    """A tiny 24 fps test clip (with a tone track by default)."""
    argv = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:s=64x64:d={seconds}:r=24"]
    if audio:
        argv += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    argv += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(argv, check=True)
    return path


def frame_count(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, check=True, text=True).stdout
    return int(out.strip().splitlines()[0])


@pytest.fixture
def media(tmp_path: Path) -> Path:
    return tmp_path


_GATEWAYS: dict[int, Cosmos3Gateway] = {}


def _gateway_of(client: TestClient) -> Cosmos3Gateway:
    return _GATEWAYS[id(client.app)]


@pytest.fixture
def client(media: Path):
    gw = Cosmos3Gateway(base_url=GW, media_dir=media)
    app = create_app(gw)
    _GATEWAYS[id(app)] = gw
    with TestClient(app) as c:
        yield c
    _GATEWAYS.pop(id(app), None)


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
    upstream.get("/jobs/video_gen_1/content").mock(return_value=httpx.Response(200, content=MP4_BYTES))   # STORY_025 caches on done
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


# --- STORY_025: the poll that reports done caches the clip ---------------------------------

def test_done_poll_caches_the_clip_once(client, upstream, media):
    upstream.get("/jobs/video_gen_9").mock(return_value=httpx.Response(200, json={"id": "video_gen_9", "status": "completed", "size": "704x1280"}))
    content = upstream.get("/jobs/video_gen_9/content").mock(return_value=httpx.Response(200, content=MP4_BYTES, headers={"content-type": "video/mp4"}))
    job = client.get("/flow/jobs/video_gen_9").json()
    assert job["status"] == "done" and job["media_id"] == "out:video_gen_9.mp4"
    assert (media / "flow-outputs" / "video_gen_9.mp4").read_bytes() == MP4_BYTES
    assert content.call_count == 1
    assert client.get("/flow/jobs/video_gen_9").json()["status"] == "done"        # second poll: no re-download
    assert client.get("/flow/media/out:video_gen_9.mp4", params={"type": "FULL"}).content == MP4_BYTES
    assert content.call_count == 1
    assert not list((media / "flow-outputs").glob("*.part"))


def test_running_poll_does_not_touch_content(client, upstream):
    upstream.get("/jobs/video_gen_9").mock(return_value=httpx.Response(200, json={"id": "video_gen_9", "status": "in_progress", "progress": 10}))
    content = upstream.get("/jobs/video_gen_9/content").mock(return_value=httpx.Response(200, content=MP4_BYTES))
    assert client.get("/flow/jobs/video_gen_9").json()["status"] == "running" and content.call_count == 0


def test_done_poll_survives_a_failed_download(client, upstream, media):
    upstream.get("/jobs/video_gen_9").mock(return_value=httpx.Response(200, json={"id": "video_gen_9", "status": "completed"}))
    content = upstream.get("/jobs/video_gen_9/content").mock(return_value=httpx.Response(404))
    assert client.get("/flow/jobs/video_gen_9").json()["status"] == "done"            # the job is still reported honestly
    assert not list((media / "flow-outputs").iterdir())
    assert client.get("/flow/media/out:video_gen_9.mp4", params={"type": "FULL"}).status_code == 404
    assert content.call_count == 2                                                    # lazy path retried


# --- STORY_026: Extend ---------------------------------------------------------------------

@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required to make the clip")
def test_generate_with_a_video_reference_extends(client, upstream, tmp_path):
    rid = upload(client, "clip.mp4", make_clip(tmp_path / "clip.mp4").read_bytes(), "video/mp4")
    route = upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_x", "status": "queued", "size": "832x480", "condition_frames": 73, "generated_frames": 192}))
    resp = client.post("/flow/generate", json={"mode": "video", "prompt": "carry on", "values": {**VALUES, "size": "832x480"}, "reference_id": rid})
    assert resp.status_code == 202, resp.text
    sent = route.calls.last.request.content
    assert b'name="video"' in sent and b'name="image"' not in sent
    assert b'name="condition_seconds"' in sent and b"\r\n3.0\r\n" in sent
    assert b"\r\n265\r\n" in sent                      # length 8 from a clip → 73 + 192
    assert resp.json()["duration_s"] == 8


def test_generate_with_an_image_reference_sends_no_condition_seconds(client, upstream):
    rid = upload(client)
    route = upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_i", "status": "queued"}))
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid}).status_code == 202
    sent = route.calls.last.request.content
    assert b'name="image"' in sent and b"condition_seconds" not in sent


def test_generate_rejects_an_unknown_reference_kind(client, tmp_path):
    rid = upload(client, "notes.gif", tiny_png(), "image/gif")          # gif is an image kind: accepted
    assert rid.endswith(".gif")
    weird = (tmp_path / "flow-uploads" / "x.bin"); weird.write_bytes(b"?")
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": "in:x.bin"}).status_code == 422


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe are required")
def test_done_extend_is_trimmed_and_raw_kept_aside(client, upstream, media, tmp_path):
    raw_clip = make_clip(tmp_path / "render.mp4", seconds=4.0)          # 96 frames + tone
    rid = upload(client, "src.mp4", make_clip(tmp_path / "src.mp4").read_bytes(), "video/mp4")
    upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_e", "status": "queued", "condition_frames": 25, "generated_frames": 71}))
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid}).status_code == 202
    upstream.get("/jobs/video_gen_e").mock(return_value=httpx.Response(200, json={"id": "video_gen_e", "status": "completed", "condition_frames": 25, "generated_frames": 71}))
    content = upstream.get("/jobs/video_gen_e/content").mock(return_value=httpx.Response(200, content=raw_clip.read_bytes(), headers={"content-type": "video/mp4"}))
    job = client.get("/flow/jobs/video_gen_e").json()
    assert job["status"] == "done" and job["media_id"] == "out:video_gen_e.mp4"
    served = media / "flow-outputs" / "video_gen_e.mp4"
    raw = media / "flow-outputs-raw" / "video_gen_e.mp4"
    assert frame_count(served) == 96 - 25 and frame_count(raw) == 96
    assert content.call_count == 1 and not list((media / "flow-outputs").glob("*.part"))
    assert [a["id"] for a in client.get("/flow/media").json() if a["source"] == "output"] == ["out:video_gen_e.mp4"]
    assert client.get("/flow/jobs/video_gen_e").json()["status"] == "done" and content.call_count == 1   # idempotent
    assert client.get("/flow/media/out:video_gen_e.mp4", params={"type": "THUMBNAIL"}).headers["content-type"].startswith("image/")


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe are required")
def test_done_generate_is_not_trimmed(client, upstream, media, tmp_path):
    raw_clip = make_clip(tmp_path / "render.mp4", seconds=2.0, audio=False)   # 48 frames, silent
    rid = upload(client)
    upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_g", "status": "queued", "condition_frames": None}))
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid}).status_code == 202
    upstream.get("/jobs/video_gen_g").mock(return_value=httpx.Response(200, json={"id": "video_gen_g", "status": "completed"}))
    upstream.get("/jobs/video_gen_g/content").mock(return_value=httpx.Response(200, content=raw_clip.read_bytes()))
    assert client.get("/flow/jobs/video_gen_g").json()["status"] == "done"
    assert frame_count(media / "flow-outputs" / "video_gen_g.mp4") == 48
    assert not (media / "flow-outputs-raw").exists()


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required to make the clip")
def test_trim_failure_serves_the_raw_clip(client, upstream, media, tmp_path, monkeypatch):
    import flow.gateway as fg
    monkeypatch.setattr(fg, "trim_prefix", lambda raw, out, n, fps=24: None)
    rid = upload(client, "src.mp4", make_clip(tmp_path / "src.mp4").read_bytes(), "video/mp4")
    upstream.post("/generate").mock(return_value=httpx.Response(200, json={"id": "video_gen_f", "status": "queued", "condition_frames": 25}))
    assert client.post("/flow/generate", json={"mode": "video", "prompt": "x", "values": VALUES, "reference_id": rid}).status_code == 202
    upstream.get("/jobs/video_gen_f").mock(return_value=httpx.Response(200, json={"id": "video_gen_f", "status": "completed"}))
    upstream.get("/jobs/video_gen_f/content").mock(return_value=httpx.Response(200, content=MP4_BYTES))
    assert client.get("/flow/jobs/video_gen_f").json()["status"] == "done"
    assert (media / "flow-outputs" / "video_gen_f.mp4").read_bytes() == MP4_BYTES       # untrimmed, but served
    assert not (media / "flow-outputs-raw" / "video_gen_f.mp4").exists()


def test_lazy_first_view_also_finalises(client, upstream, media, monkeypatch):
    """A cache wiped by hand: the first /flow/media access re-fetches through the same finaliser."""
    import flow.gateway as fg
    seen: list[tuple] = []
    monkeypatch.setattr(fg, "trim_prefix", lambda raw, out, n, fps=24: seen.append((raw.name, out.name, n)) or out.write_bytes(b"trimmed") or out)
    upstream.get("/jobs/video_gen_l/content").mock(return_value=httpx.Response(200, content=MP4_BYTES))
    gw = _gateway_of(client)      # remember an extend job without going through /generate
    gw._meta_by_job["video_gen_l"] = {"size": "832x480", "length": 8.0, "condition_frames": 73}
    resp = client.get("/flow/media/out:video_gen_l.mp4", params={"type": "FULL"})
    assert resp.status_code == 200 and resp.content == b"trimmed"
    assert seen == [("video_gen_l.mp4", "video_gen_l.mp4", 73)]
    assert (media / "flow-outputs-raw" / "video_gen_l.mp4").read_bytes() == MP4_BYTES
