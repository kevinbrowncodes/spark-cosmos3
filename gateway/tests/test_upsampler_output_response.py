"""Unit/contract tests for surfacing upsampler_output in responses (STORY_016).

Covers: upsampler_output present + equal to the structured prompt on the
upsampled path; null on the prose/disabled path and on upsample failure/
fallback; /jobs/{id} echoes the same value from _JOB_META.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))
os.environ.setdefault("LOG_DIR", "/tmp/cosmos-test-logs")

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.testclient import TestClient
import server

_SMALL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

_STRUCTURED = '{"subjects": [{"name": "cat"}], "audio_description": "purr"}'


def _post(upsample="true", upsample_result=None):
    """Drive POST /generate with the engine + upsampler mocked.

    upsample_result: the (structured, fallback_reason, meta) tuple returned by
    the mocked upsampler.upsample. Defaults to a successful upsample.
    """
    if upsample_result is None:
        upsample_result = (_STRUCTURED, None, {"reasoner": "opus", "upsample_attempts": 1})

    cosmos_resp = MagicMock()
    cosmos_resp.status_code = 200
    cosmos_resp.json.return_value = {"id": "job-016", "status": "queued", "progress": 0}

    async def engine_post(url, data=None, files=None, **kw):
        return cosmos_resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=engine_post)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=upsample_result)),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            resp = client.post(
                "/generate",
                data={"prompt": "a cat", "upsample": upsample},
                files={"image": ("t.png", _SMALL_PNG, "image/png")},
            )
    return resp


class TestGenerateResponse:
    def test_upsampled_path_returns_structured_prompt(self):
        resp = _post(upsample="true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt_source"] == "upsampled"
        assert body["upsampler_output"] == _STRUCTURED

    def test_disabled_path_returns_null(self):
        resp = _post(
            upsample="false",
            upsample_result=(None, "disabled_by_request", None),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt_source"] == "prose"
        assert body["upsampler_output"] is None

    def test_fallback_returns_null_not_prose(self):
        # Upsample attempted but failed -> gateway falls back to prose. The
        # field must be null, never the raw prose brief.
        resp = _post(
            upsample="true",
            upsample_result=(None, "invalid_json", {"reasoner": "opus"}),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt_source"] == "prose"
        assert body["upsampler_output"] is None


class TestJobStatusEcho:
    def test_jobs_endpoint_echoes_upsampler_output(self):
        # Submit first so _JOB_META is populated for job-016.
        _post(upsample="true")

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {"id": "job-016", "status": "queued", "progress": 0}

        async def engine_get(url, **kw):
            return status_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=engine_get)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_cm):
            with TestClient(server.app) as client:
                resp = client.get("/jobs/job-016")

        assert resp.status_code == 200
        assert resp.json()["upsampler_output"] == _STRUCTURED
