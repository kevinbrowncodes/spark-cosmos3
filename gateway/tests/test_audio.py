"""Unit + contract tests for audio toggle behaviour (STORY_001)."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# DATA_DIR and LOG_DIR must be set before server is imported (resolved at module load)
_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))
os.environ.setdefault("LOG_DIR", "/tmp/cosmos-test-logs")

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from starlette.testclient import TestClient

import server

# Minimal 1×1 PNG so multipart upload doesn't reject the file field
_SMALL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_cosmos_client_mock(captured_form: dict) -> MagicMock:
    """
    Return a mock for httpx.AsyncClient that intercepts the cosmos POST,
    records the submitted form data into `captured_form`, and returns a
    fake queued-job response.
    """
    cosmos_response = MagicMock()
    cosmos_response.status_code = 200
    cosmos_response.json.return_value = {"id": "test-id", "status": "queued", "progress": 0}

    async def capture_post(url, data=None, files=None, **kw):
        captured_form.update(data or {})
        return cosmos_response

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=capture_post)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


def _post_generate(generate_sound: bool) -> tuple[dict, dict]:
    """Submit /generate and return (response_json, captured_cosmos_form)."""
    captured: dict = {}
    mock_cm = _make_cosmos_client_mock(captured)

    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=(None, "disabled_by_request"))),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            resp = client.post(
                "/generate",
                data={
                    "prompt": "a cat walks slowly",
                    "generate_sound": str(generate_sound).lower(),
                    "num_inference_steps": "4",
                    "upsample": "false",
                },
                files={"input_reference": ("test.png", _SMALL_PNG, "image/png")},
            )

    assert resp.status_code == 200, resp.text
    return resp.json(), captured


# ---------------------------------------------------------------------------
# GET /audio
# ---------------------------------------------------------------------------

class TestGetAudio:
    def test_returns_200(self):
        with TestClient(server.app) as client:
            r = client.get("/audio")
        assert r.status_code == 200

    def test_has_default_enabled_true(self):
        with TestClient(server.app) as client:
            r = client.get("/audio")
        assert r.json()["default_enabled"] is True

    def test_directive_matches_audio_txt(self):
        expected = (server.DATA / "audio.txt").read_text().strip()
        with TestClient(server.app) as client:
            r = client.get("/audio")
        assert r.json()["directive"] == expected

    def test_directive_contains_audio_marker(self):
        with TestClient(server.app) as client:
            r = client.get("/audio")
        assert "AUDIO:" in r.json()["directive"]


# ---------------------------------------------------------------------------
# POST /generate — audio directive in forwarded prompt
# ---------------------------------------------------------------------------

class TestAudioDirectiveInGenerate:
    def test_audio_directive_appended_when_sound_on(self):
        audio_txt = (server.DATA / "audio.txt").read_text().strip()
        _, form = _post_generate(generate_sound=True)
        assert audio_txt in form["prompt"]

    def test_audio_directive_omitted_when_sound_off(self):
        audio_txt = (server.DATA / "audio.txt").read_text().strip()
        _, form = _post_generate(generate_sound=False)
        assert audio_txt not in form["prompt"]

    def test_generate_sound_false_still_sends_sound_duration(self):
        _, form = _post_generate(generate_sound=False)
        assert form.get("generate_sound") == "false"
        assert "sound_duration" in form
