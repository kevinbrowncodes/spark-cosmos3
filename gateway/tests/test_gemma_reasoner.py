"""Unit/contract tests for the local Gemma reasoner (STORY_022).

Covers: gemma as the default, aeon's removal, opus still selectable, and — the
crux — that retries cover CONTENT failures. The pre-existing retry policy only
caught transport errors, which is correct for Opus (72/72 valid in the job logs)
and wrong for Gemma, whose failure mode is HTTP 200 carrying malformed JSON.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))
os.environ.setdefault("LOG_DIR", "/tmp/cosmos-test-logs")

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.testclient import TestClient
import server
import upsampler

from tests.helpers import make_clip

_SMALL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _valid_structured() -> dict:
    d = {k: "x" for k in upsampler.CANONICAL_KEYS}
    d["subjects"] = [{"description": "a person"}]
    d["temporal_caption"] = "the scene continues forward"
    d["audio_description"] = "quiet room tone"
    return d


def _gemma_reply(content: str) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


def _client_returning(*responses):
    """An httpx.AsyncClient stub yielding the given responses in order."""
    seq = list(responses)
    calls = {"n": 0}

    async def post(url, **kw):
        calls["n"] += 1
        return seq[min(calls["n"] - 1, len(seq) - 1)]

    c = AsyncMock()
    c.post = AsyncMock(side_effect=post)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=c)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, calls


class TestValidation:
    def test_accepts_a_well_formed_prompt(self):
        upsampler.validate_structured(_valid_structured())

    def test_rejects_the_forbidden_scene_imagination_key(self):
        d = _valid_structured() | {"scene_imagination": "..."}
        with pytest.raises(ValueError, match="extra keys"):
            upsampler.validate_structured(d)

    def test_rejects_missing_keys(self):
        d = _valid_structured()
        del d["segments"]
        with pytest.raises(ValueError, match="missing keys"):
            upsampler.validate_structured(d)

    @pytest.mark.parametrize("field", ["temporal_caption", "audio_description"])
    def test_rejects_empty_required_text(self, field):
        d = _valid_structured() | {field: "   "}
        with pytest.raises(ValueError, match=field):
            upsampler.validate_structured(d)

    def test_rejects_empty_subjects(self):
        with pytest.raises(ValueError, match="subjects"):
            upsampler.validate_structured(_valid_structured() | {"subjects": []})


class TestContentRetries:
    """The behaviour the old policy lacked entirely."""

    @pytest.mark.asyncio
    async def test_malformed_json_is_retried_then_succeeds(self):
        good = json.dumps(_valid_structured())
        cm, calls = _client_returning(_gemma_reply("{not json,,,"), _gemma_reply(good))
        with patch("httpx.AsyncClient", return_value=cm):
            out, reason, meta = await upsampler.upsample(
                prompt="p", image_bytes=b"\xff\xd8x", size="832x480", num_frames=241,
                fps=24, generate_sound=True,
            )
        assert reason is None and out
        assert calls["n"] == 2, "a parse failure must trigger a retry"
        assert meta["upsample_attempts"] == 2

    @pytest.mark.asyncio
    async def test_empty_content_counts_as_failure(self):
        # Gemma at low max_tokens returns "" with a populated `reasoning` field.
        good = json.dumps(_valid_structured())
        cm, calls = _client_returning(_gemma_reply(""), _gemma_reply(good))
        with patch("httpx.AsyncClient", return_value=cm):
            out, reason, _ = await upsampler.upsample(
                prompt="p", image_bytes=b"\xff\xd8x", size="832x480", num_frames=241,
                fps=24, generate_sound=True,
            )
        assert reason is None and out
        assert calls["n"] == 2, "empty content must not be treated as success"

    @pytest.mark.asyncio
    async def test_schema_violation_is_retried(self):
        bad = json.dumps(_valid_structured() | {"scene_imagination": "..."})
        good = json.dumps(_valid_structured())
        cm, calls = _client_returning(_gemma_reply(bad), _gemma_reply(good))
        with patch("httpx.AsyncClient", return_value=cm):
            out, reason, _ = await upsampler.upsample(
                prompt="p", image_bytes=b"\xff\xd8x", size="832x480", num_frames=241,
                fps=24, generate_sound=True,
            )
        assert reason is None and calls["n"] == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_fall_back_to_prose_not_500(self):
        cm, calls = _client_returning(_gemma_reply("{broken"))
        with patch("httpx.AsyncClient", return_value=cm):
            out, reason, meta = await upsampler.upsample(
                prompt="p", image_bytes=b"\xff\xd8x", size="832x480", num_frames=241,
                fps=24, generate_sound=True,
            )
        assert out is None and reason == "invalid_json"
        assert calls["n"] == upsampler._GEMMA_ATTEMPTS
        assert meta["upsample_attempts"] == upsampler._GEMMA_ATTEMPTS


class TestReasonerSelection:
    def test_gemma_is_the_default(self):
        import inspect
        assert inspect.signature(upsampler.upsample).parameters["reasoner"].default == "gemma"
        assert server._VALID_REASONERS[0] == "gemma"

    def test_opus_is_still_selectable(self):
        assert "opus" in server._VALID_REASONERS

    def test_aeon_is_removed(self):
        assert "aeon" in server._REMOVED_REASONERS
        assert not hasattr(upsampler, "AEON_URL")
        assert not hasattr(upsampler, "_upsample_aeon")


def _post(files, data=None):
    captured = {}
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": "job-022", "status": "queued", "progress": 0}

    async def engine_post(url, data=None, files=None, **kw):
        captured["data"] = data
        return resp

    c = AsyncMock()
    c.post = AsyncMock(side_effect=engine_post)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=c)
    cm.__aexit__ = AsyncMock(return_value=False)

    payload = {"prompt": "the scene continues", "size": "832x480"}
    payload.update(data or {})
    with (
        patch("httpx.AsyncClient", return_value=cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=('{"subjects":[]}', None, {"reasoner": "gemma"}))),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            r = client.post("/generate", data=payload, files=files)
    return r, captured


class TestGatewayContract:
    def test_no_reasoner_field_uses_gemma(self):
        r, _ = _post({"image": ("t.png", _SMALL_PNG, "image/png")}, {"frames": "240"})
        assert r.status_code == 200
        assert r.json()["prompt_source"] == "upsampled"

    def test_aeon_is_rejected_with_a_message_naming_the_removal(self):
        r, _ = _post({"image": ("t.png", _SMALL_PNG, "image/png")},
                     {"frames": "240", "reasoner": "aeon"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "removed" in detail.lower() and "gemma" in detail

    def test_unknown_reasoner_still_422s(self):
        r, _ = _post({"image": ("t.png", _SMALL_PNG, "image/png")},
                     {"frames": "240", "reasoner": "llama"})
        assert r.status_code == 422

    def test_opus_still_routes(self):
        r, _ = _post({"image": ("t.png", _SMALL_PNG, "image/png")},
                     {"frames": "240", "reasoner": "opus"})
        assert r.status_code == 200
