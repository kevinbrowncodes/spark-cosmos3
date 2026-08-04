"""Unit tests for upsampler retry logic (STORY_014).

Tests cover: transient-error retry on 529/429/5xx/connection errors,
no-retry on deterministic 4xx, upsample_attempts count in meta.
"""

import asyncio
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
# Schema-complete, as real Opus output is (72/72 valid in the job logs).
# STORY_022 validates the full canonical key set on both reasoner paths,
# so the previous minimal stub no longer represents a passing response.
_VALID_JSON = '```json\n{"actions": [], "aesthetics": "x", "artistic_style": "x", "aspect_ratio": "x", "audio_description": "quiet room tone", "background_setting": "x", "cinematography": "x", "context": "x", "duration": "x", "fps": 24, "lighting": "x", "resolution": {}, "segments": [], "style_medium": "x", "subjects": [{"name": "t"}], "temporal_caption": "the scene continues", "text_and_signage_elements": [], "transitions": []}\n```'


def _make_message(text=_VALID_JSON, stop_reason="end_turn"):
    msg = MagicMock()
    msg.stop_reason = stop_reason
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg.content = [block]
    msg.usage = MagicMock(input_tokens=10, output_tokens=20)
    return msg


def _status_error(code):
    """Build a real anthropic.APIStatusError with the given HTTP status code."""
    import anthropic as _a
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(code, request=request)
    return _a.APIStatusError("error", response=response, body={})


def _connection_error():
    import anthropic as _a
    return _a.APIConnectionError.__new__(_a.APIConnectionError)


def _run_upsample(**kwargs):
    defaults = dict(
        prompt="a sunset",
        image_bytes=_FAKE_IMAGE,
        size=_VALID_SIZE,
        num_frames=_VALID_FRAMES,
        fps=24,
        generate_sound=True,
        reasoner="opus",
    )
    defaults.update(kwargs)
    return asyncio.run(upsampler.upsample(**defaults))


class TestOpusRetryOnTransientErrors:
    def test_529_twice_then_success_returns_attempts_3(self):
        calls = [_status_error(529), _status_error(529), _make_message()]

        async def side_effect(**kw):
            val = calls.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = side_effect

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result, reason, meta = _run_upsample()

        assert result is not None
        assert reason is None
        assert meta["upsample_attempts"] == 3
        assert meta["reasoner"] == "opus"

    def test_529_three_times_falls_back_to_prose_with_attempts_3(self):
        calls = [_status_error(529), _status_error(529), _status_error(529)]

        async def side_effect(**kw):
            raise calls.pop(0)

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = side_effect

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result, reason, meta = _run_upsample()

        assert result is None
        assert reason is not None and "api_error" in reason
        assert meta["upsample_attempts"] == 3

    def test_429_triggers_retry(self):
        calls = [_status_error(429), _make_message()]

        async def side_effect(**kw):
            val = calls.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = side_effect

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result, reason, meta = _run_upsample()

        assert result is not None
        mock_sleep.assert_called_once()
        assert meta["upsample_attempts"] == 2

    def test_400_no_retry_immediate_fallback(self):
        calls = [_status_error(400)]

        async def side_effect(**kw):
            raise calls.pop(0)

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = side_effect

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result, reason, meta = _run_upsample()

        assert result is None
        mock_sleep.assert_not_called()
        assert meta["upsample_attempts"] == 1

    def test_413_no_retry_immediate_fallback(self):
        calls = [_status_error(413)]

        async def side_effect(**kw):
            raise calls.pop(0)

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = side_effect

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result, reason, meta = _run_upsample()

        assert result is None
        mock_sleep.assert_not_called()
        assert meta["upsample_attempts"] == 1

    def test_connection_error_triggers_retry(self):
        import anthropic as _a

        conn_err = _a.APIConnectionError.__new__(_a.APIConnectionError)
        calls = [conn_err, _make_message()]

        async def side_effect(**kw):
            val = calls.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = side_effect

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result, reason, meta = _run_upsample()

        assert result is not None
        mock_sleep.assert_called_once()
        assert meta["upsample_attempts"] == 2

    def test_success_on_first_attempt_has_attempts_1(self):
        mock_client = MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_make_message())

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("upsampler._get_client", return_value=mock_client):
                result, reason, meta = _run_upsample()

        assert result is not None
        assert meta["upsample_attempts"] == 1
