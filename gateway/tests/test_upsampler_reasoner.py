"""Unit tests for selectable reasoner (STORY_015).

Tests cover: opus/aeon routing, invalid reasoner → 422, aeon unreachable → 503,
reasoner recorded in provenance.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pytest
import upsampler

_FAKE_IMAGE = b"\xff\xd8" + b"\x00" * 10
_VALID_SIZE = "720x1280"
_VALID_FRAMES = 189
_VALID_JSON = (
    '```json\n{"subjects": [{"name": "t"}], "actions": [], "environment": {}, '
    '"cinematography": {}, "resolution": {}, "aspect_ratio": "", '
    '"duration": "", "fps": 24, "audio_description": ""}\n```'
)


def _make_opus_message(text=_VALID_JSON):
    msg = MagicMock()
    msg.stop_reason = "end_turn"
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg.content = [block]
    msg.usage = MagicMock(input_tokens=10, output_tokens=20)
    return msg


def _make_aeon_response(text=_VALID_JSON, status=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = {"choices": [{"message": {"content": text}}]}
    resp.raise_for_status = MagicMock()
    return resp


def _run_upsample(**kwargs):
    defaults = dict(
        prompt="a sunset",
        image_bytes=_FAKE_IMAGE,
        size=_VALID_SIZE,
        num_frames=_VALID_FRAMES,
        fps=24,
        generate_sound=True,
    )
    defaults.update(kwargs)
    return asyncio.run(upsampler.upsample(**defaults))


class TestReasonerRouting:
    def test_default_reasoner_calls_opus(self):
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_make_opus_message())

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("httpx.AsyncClient") as mock_httpx:
                    result, reason, meta = _run_upsample()

        assert result is not None
        assert meta["reasoner"] == "opus"
        mock_httpx.assert_not_called()

    def test_reasoner_opus_explicit_calls_opus(self):
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_make_opus_message())

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("httpx.AsyncClient") as mock_httpx:
                    result, reason, meta = _run_upsample(reasoner="opus")

        assert result is not None
        assert meta["reasoner"] == "opus"
        mock_httpx.assert_not_called()

    def test_reasoner_aeon_calls_aeon_not_opus(self):
        mock_resp = _make_aeon_response()
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("upsampler._get_client") as mock_get_client:
            with patch("httpx.AsyncClient", return_value=mock_http_client):
                result, reason, meta = _run_upsample(reasoner="aeon")

        assert result is not None
        assert meta["reasoner"] == "aeon"
        mock_get_client.assert_not_called()

    def test_aeon_meta_contains_endpoint(self):
        mock_resp = _make_aeon_response()
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result, reason, meta = _run_upsample(reasoner="aeon")

        assert "endpoint" in meta
        assert "8003" in meta["endpoint"]

    def test_aeon_unreachable_returns_aeon_unreachable_reason(self):
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result, reason, meta = _run_upsample(reasoner="aeon")

        assert result is None
        assert reason == "aeon_unreachable"
        assert meta["reasoner"] == "aeon"

    def test_aeon_provenance_contains_reasoner(self):
        mock_resp = _make_aeon_response()
        mock_http_client = AsyncMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)
        mock_http_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            result, reason, meta = _run_upsample(reasoner="aeon")

        assert meta["reasoner"] == "aeon"
        assert meta["upsample_attempts"] == 1


class TestInvalidReasonerRejectedByServer:
    def test_bad_reasoner_returns_422(self):
        from fastapi.testclient import TestClient
        import server

        client = TestClient(server.app)
        resp = client.post(
            "/generate",
            data={"prompt": "test", "reasoner": "badvalue"},
            files={"image": ("t.png", _FAKE_IMAGE, "image/png")},
        )
        assert resp.status_code == 422
        assert "badvalue" in resp.text

    def test_aeon_unreachable_returns_503(self):
        from fastapi.testclient import TestClient
        import server

        client = TestClient(server.app)

        async def fake_upsample(**kwargs):
            return None, "aeon_unreachable", {"reasoner": "aeon", "upsample_attempts": 1}

        with patch("upsampler.upsample", side_effect=fake_upsample):
            resp = client.post(
                "/generate",
                data={"prompt": "test", "reasoner": "aeon"},
                files={"image": ("t.png", _FAKE_IMAGE, "image/png")},
            )

        assert resp.status_code == 503
