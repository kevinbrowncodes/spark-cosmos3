"""Contract tests for num_inference_steps validation (STORY_011)."""

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


def _post(steps=None):
    cosmos_resp = MagicMock()
    cosmos_resp.status_code = 200
    cosmos_resp.json.return_value = {"id": "test-id", "status": "queued", "progress": 0}

    captured = {}

    async def capture_post(url, data=None, files=None, **kw):
        captured.update(data or {})
        return cosmos_resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=capture_post)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    data = {"prompt": "test", "upsample": "false"}
    if steps is not None:
        data["steps"] = str(steps)

    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=(None, "disabled_by_request", None))),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            resp = client.post(
                "/generate",
                data=data,
                files={"image": ("test.png", _SMALL_PNG, "image/png")},
            )
    return resp, captured


class TestInferenceStepsValidation:
    def test_default_is_35(self):
        resp, form = _post(steps=None)
        assert resp.status_code == 200
        assert form.get("num_inference_steps") == "35"

    def test_35_accepted(self):
        resp, _ = _post(steps=35)
        assert resp.status_code == 200

    def test_50_accepted(self):
        resp, form = _post(steps=50)
        assert resp.status_code == 200
        assert form.get("num_inference_steps") == "50"

    def test_4_rejected(self):
        resp, _ = _post(steps=4)
        assert resp.status_code == 400

    def test_20_rejected(self):
        resp, _ = _post(steps=20)
        assert resp.status_code == 400

    def test_100_rejected(self):
        resp, _ = _post(steps=100)
        assert resp.status_code == 400

    def test_error_message_mentions_valid_values(self):
        resp, _ = _post(steps=4)
        assert "35" in resp.json()["detail"]
        assert "50" in resp.json()["detail"]
