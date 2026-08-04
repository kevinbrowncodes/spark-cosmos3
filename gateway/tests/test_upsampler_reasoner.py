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
# Schema-complete: STORY_022 validates the full canonical key set on both
# reasoner paths, so the old minimal stub no longer represents a pass.
_VALID_JSON = '```json\n{"actions": [], "aesthetics": "x", "artistic_style": "x", "aspect_ratio": "x", "audio_description": "room tone", "background_setting": "x", "cinematography": "x", "context": "x", "duration": "x", "fps": 24, "lighting": "x", "resolution": {}, "segments": [], "style_medium": "x", "subjects": [{"name": "t"}], "temporal_caption": "the scene continues", "text_and_signage_elements": [], "transitions": []}\n```'


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
    def test_default_reasoner_is_gemma_not_opus(self):
        """STORY_022 flipped the default. Opus must not be reached implicitly."""
        called = {}

        async def fake_gemma(*a, **kw):
            called["gemma"] = True
            return "{}", None, {"reasoner": "gemma"}

        async def fake_opus(*a, **kw):
            called["opus"] = True
            return "{}", None, {"reasoner": "opus"}

        with (
            patch("upsampler._upsample_gemma", new=fake_gemma),
            patch("upsampler._upsample_opus", new=fake_opus),
        ):
            _, _, meta = _run_upsample()

        assert called.get("gemma") is True
        assert "opus" not in called, "opus must never be reached without being asked for"
        assert meta["reasoner"] == "gemma"

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

