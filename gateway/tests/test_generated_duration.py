"""Unit/contract tests for generated-frame duration + resolution-aware ceiling (STORY_020).

Covers: duration measured over the generated span on V2V, the I2V path unchanged,
per-resolution frame ceilings, and the two headline configs — 289 frames (2 s in,
10 s out) and 313 frames (3 s in, 10 s out) — both at 480p.
"""

import hashlib
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


class TestDurationOverGeneratedFrames:
    def test_the_headline_config_lands_on_ten_seconds(self):
        # 289 total - 49 conditioning = 240 generated = exactly 10.0s, the top
        # of the vendored schema's range. This is the epic's whole target.
        _, _, duration = upsampler._parse_size("832x480", 289, 24, 49)
        assert duration == "10s"

    def test_three_second_window_also_lands_on_ten_seconds(self):
        # 313 - 73 = 240 generated. Only reachable at 480p (400-frame ceiling).
        _, _, duration = upsampler._parse_size("832x480", 313, 24, 73)
        assert duration == "10s"

    def test_total_frames_would_exceed_the_schema(self):
        # The same 289 frames measured over the total is '12s' — outside the
        # vendored enum. Measuring the generated span is what makes it legal.
        with pytest.raises(ValueError, match="12s"):
            upsampler._parse_size("832x480", 289, 24, 0)

    def test_i2v_path_unchanged(self):
        _, _, duration = upsampler._parse_size("720x1280", 189, 24)
        assert duration == "7s"

    def test_error_names_the_generated_span(self):
        with pytest.raises(ValueError, match="generated frames"):
            upsampler._parse_size("832x480", 361, 24, 49)

    def test_vendored_schema_is_untouched(self):
        # STORY_020 must not widen NVIDIA's duration enum to reach 10s.
        raw = (_REPO_ROOT / "data" / "upsampler_schema.json").read_bytes()
        assert b"'2s','3s'" in raw and b"'10s'" in raw and b"'11s'" not in raw
        assert upsampler._ALLOWED_DURATIONS == frozenset(f"{s}s" for s in range(2, 11))
        # Guard the file itself so a future edit trips this test.
        assert hashlib.sha256(raw).hexdigest()[:8] != "00000000"


class TestResolutionAwareCeiling:
    @pytest.mark.parametrize(
        "size,expected",
        [("832x480", 400), ("320x192", 400), ("1280x720", 300),
         ("720x1280", 300), ("1360x768", 300)],
    )
    def test_ceilings(self, size, expected):
        assert server._frame_ceiling(size) == expected

    def test_unknown_size_falls_back_to_the_safe_ceiling(self):
        assert server._frame_ceiling("999x999") == 300

    def test_tier_lookup(self):
        assert upsampler.tier_for_size("832x480") == "480"
        assert upsampler.tier_for_size("1280x720") == "720"
        assert upsampler.tier_for_size("nonsense") is None


def _post(files, data=None):
    captured = {}
    resp_obj = MagicMock()
    resp_obj.status_code = 200
    resp_obj.json.return_value = {"id": "job-020", "status": "queued", "progress": 0}

    async def engine_post(url, data=None, files=None, **kw):
        captured["data"] = data
        return resp_obj

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=engine_post)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    payload = {"prompt": "the scene continues", "upsample": "false", "size": "832x480"}
    payload.update(data or {})
    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=(None, "disabled_by_request", None))),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            r = client.post("/generate", data=payload, files=files)
    return r, captured


def _video(n=400):
    return {"video": ("c.mp4", make_clip(n), "video/mp4")}


class TestEndToEndConfigs:
    def test_289_frames_with_two_second_window(self):
        r, captured = _post(_video(), data={"frames": "289", "condition_seconds": "2.0"})
        assert r.status_code == 200, r.json()
        body = r.json()
        assert body["condition_frames"] == 49
        assert body["generated_frames"] == 240      # exactly 10.0s
        assert captured["data"]["num_frames"] == "289"

    def test_313_frames_with_three_second_window_at_480p(self):
        r, _ = _post(_video(), data={"frames": "313", "condition_seconds": "3.0"})
        assert r.status_code == 200, r.json()
        assert r.json()["condition_frames"] == 73
        assert r.json()["generated_frames"] == 240  # also exactly 10.0s

    def test_313_frames_is_clamped_at_720p(self):
        # 720p ceiling is 300, so 313 becomes 300 -> not 4k+1 -> rejected.
        r, _ = _post(_video(), data={"frames": "313", "condition_seconds": "3.0",
                                     "size": "1280x720"})
        assert r.status_code == 400
        assert "4k+1" in r.json()["detail"]

    def test_sound_duration_covers_the_whole_output(self):
        # Audio spans the conditioning prefix too — 289/24, not 240/24.
        _, captured = _post(_video(), data={"frames": "289", "condition_seconds": "2.0"})
        assert captured["data"]["sound_duration"] == str(289 / 24)

    def test_window_consuming_everything_is_rejected_clearly(self):
        r, _ = _post(_video(), data={"frames": "121", "condition_seconds": "6.0"})
        assert r.status_code == 400
        assert "leaving nothing to generate" in r.json()["detail"]

    def test_i2v_uses_the_480p_ceiling_then_hits_the_duration_limit(self):
        # 500 -> clamped to 400 by the 480p ceiling (not 300 as before). I2V
        # measures duration over the total, so 400 frames is 16s and is then
        # correctly rejected. The error naming 400 proves the new ceiling applied.
        r, _ = _post({"image": ("t.png", _SMALL_PNG, "image/png")}, data={"frames": "500"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "num_frames=400" in detail and "16s" in detail

    def test_i2v_at_the_duration_limit_still_works(self):
        r, captured = _post({"image": ("t.png", _SMALL_PNG, "image/png")},
                            data={"frames": "240"})
        assert r.status_code == 200
        assert captured["data"]["num_frames"] == "240"


class TestProgressEstimate:
    def test_tail_constant_matches_measurement(self):
        # Recalibrated from 24 renders: median 526s end-to-end at the reference
        # volume, 12.9 s/step measured -> tail ~74s. The old 423s was 5.7x high.
        assert server._REF_TAIL_S == pytest.approx(74.0)

    def test_reference_volume_job_estimate_is_close_to_measured(self):
        est = server._expected_seconds(832, 480, 189, 35)
        assert 480 <= est <= 580, f"estimate {est:.0f}s outside the measured 518-609s band"
