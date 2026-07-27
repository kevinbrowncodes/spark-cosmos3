"""Unit/contract tests for the V2V conditioning window (STORY_018).

Covers: the seconds -> latent-index translation and its upward quantisation,
tail trimming (the assertion this story turns on), the guards that stop a
silently-frozen render, and that the I2V path is untouched.
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
import video as video_util

from tests.helpers import first_frame_luma, frame_count, make_clip

_SMALL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestConditionWindow:
    """Latent indexes quantise upward — 4 pixel frames per latent frame."""

    @pytest.mark.parametrize(
        "seconds,expected_max_index,expected_frames",
        [
            (0.2, 1, 5),    # the engine's own default: (0, 1)
            (1.0, 6, 25),
            (2.0, 12, 49),  # the epic's target — note 49, not 48
            (3.0, 18, 73),  # the Physics-IQ V2V protocol's 3 s
        ],
    )
    def test_translation(self, seconds, expected_max_index, expected_frames):
        indexes, frames = video_util.condition_window(seconds, 24)
        assert indexes == tuple(range(expected_max_index + 1))
        assert frames == expected_frames

    def test_two_seconds_quantises_up_not_down(self):
        # 2.000 s is 48 frames; the window is 49. A client that pre-trims to
        # exactly 2.000 s arrives one frame short — the trap documented in the
        # story. Truncating down instead would silently shorten conditioning.
        _, frames = video_util.condition_window(2.0, 24)
        assert frames == 49 > round(2.0 * 24)

    def test_tiny_request_clamps_to_the_engine_floor(self):
        indexes, frames = video_util.condition_window(0.01, 24)
        assert indexes == (0, 1) and frames == 5


class TestTailTrimming:
    def test_keeps_the_last_frames_not_the_first(self):
        # The assertion this story exists for. Source frame 140 has luma 255
        # (clamped); frame 0 has luma 0. If we kept the head, luma would be ~0.
        clip = make_clip(189)
        trimmed, total, fps = video_util.prepare_tail(clip, 49)
        assert total == 189 and fps == 24.0
        assert frame_count(trimmed) == 49
        assert first_frame_luma(trimmed) > 200, "trimmed clip starts at the head, not the tail"
        assert first_frame_luma(clip) < 20

    def test_exact_length_clip_is_returned_untouched(self):
        clip = make_clip(49)
        trimmed, total, _ = video_util.prepare_tail(clip, 49)
        assert trimmed is clip, "re-encoding a correctly-sized clip loses a generation"
        assert total == 49

    def test_short_clip_is_rejected(self):
        with pytest.raises(video_util.ClipError, match="30 frames but the conditioning window needs 49"):
            video_util.prepare_tail(make_clip(30), 49)

    def test_wrong_frame_rate_is_rejected_naming_the_rate(self):
        with pytest.raises(video_util.ClipError, match="30.000 fps"):
            video_util.prepare_tail(make_clip(60, fps=30), 49)

    def test_undecodable_input_is_rejected(self):
        with pytest.raises(video_util.ClipError, match="could not decode"):
            video_util.prepare_tail(b"not a video at all", 5)

    def test_frames_are_counted_by_decoding_not_metadata(self):
        # The engine walks container.decode(); nb_frames in the header can be
        # absent or wrong. Counting must agree with the engine or the guard is
        # meaningless.
        clip = make_clip(60)
        _, total, _ = video_util.prepare_tail(clip, 5)
        assert total == frame_count(clip) == 60


def _post(files, data=None):
    captured = {}
    cosmos_resp = MagicMock()
    cosmos_resp.status_code = 200
    cosmos_resp.json.return_value = {"id": "job-018", "status": "queued", "progress": 0}

    async def engine_post(url, data=None, files=None, **kw):
        captured["data"] = data
        captured["files"] = files
        return cosmos_resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=engine_post)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    payload = {"prompt": "the scene continues", "upsample": "false"}
    payload.update(data or {})

    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=(None, "disabled_by_request", None))),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            resp = client.post("/generate", data=payload, files=files)
    return resp, captured


def _video(n_frames=189, fps=24):
    return {"video": ("clip.mp4", make_clip(n_frames, fps), "video/mp4")}


_IMAGE = {"image": ("t.png", _SMALL_PNG, "image/png")}


class TestGenerateContract:
    def test_two_seconds_reports_the_quantised_split(self):
        resp, _ = _post(_video(), data={"condition_seconds": "2.0", "frames": "189"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["condition_frames"] == 49
        assert body["generated_frames"] == 140
        assert body["condition_frames"] + body["generated_frames"] == 189

    def test_indexes_reach_the_engine_in_extra_params(self):
        _, captured = _post(_video(), data={"condition_seconds": "2.0"})
        extra = json.loads(captured["data"]["extra_params"])
        assert extra["condition_frame_indexes_vision"] == "0,1,2,3,4,5,6,7,8,9,10,11,12"
        # The house contract must survive alongside the new key.
        assert extra["guardrails"] is False
        assert extra["use_resolution_template"] is False
        assert extra["use_duration_template"] is False

    def test_forwarded_clip_is_the_trimmed_tail(self):
        _, captured = _post(_video(189), data={"condition_seconds": "2.0"})
        forwarded = captured["files"]["input_reference"][1]
        assert frame_count(forwarded) == 49
        assert first_frame_luma(forwarded) > 200

    def test_default_matches_the_engine_five_frame_window(self):
        resp, captured = _post(_video())
        assert resp.json()["condition_frames"] == 5
        extra = json.loads(captured["data"]["extra_params"])
        assert extra["condition_frame_indexes_vision"] == "0,1"

    def test_short_clip_is_a_400(self):
        resp, _ = _post(_video(30), data={"condition_seconds": "2.0"})
        assert resp.status_code == 400
        assert "conditioning window needs 49" in resp.json()["detail"]

    def test_wrong_fps_is_a_400(self):
        resp, _ = _post(_video(120, fps=30), data={"condition_seconds": "2.0"})
        assert resp.status_code == 400
        assert "30.000 fps" in resp.json()["detail"]

    def test_window_larger_than_output_is_a_400(self):
        resp, _ = _post(_video(), data={"condition_seconds": "8.0", "frames": "189"})
        assert resp.status_code == 400
        assert "leaving nothing to generate" in resp.json()["detail"]

    def test_non_positive_is_a_400(self):
        resp, _ = _post(_video(), data={"condition_seconds": "0"})
        assert resp.status_code == 400

    def test_condition_seconds_with_image_is_a_400(self):
        resp, _ = _post(_IMAGE, data={"condition_seconds": "2.0"})
        assert resp.status_code == 400
        assert "video-to-video only" in resp.json()["detail"]


class TestI2VUntouched:
    def test_extra_params_is_the_frozen_string(self):
        _, captured = _post(_IMAGE)
        assert captured["data"]["extra_params"] == server.EXTRA_PARAMS
        assert "condition_frame_indexes_vision" not in captured["data"]["extra_params"]

    def test_image_bytes_are_forwarded_unmodified(self):
        _, captured = _post(_IMAGE)
        assert captured["files"]["input_reference"][1] == _SMALL_PNG

    def test_split_fields_are_null(self):
        body = _post(_IMAGE)[0].json()
        assert body["condition_frames"] is None
        assert body["generated_frames"] is None


class TestJobStatusEcho:
    def test_jobs_endpoint_echoes_the_split(self):
        _post(_video(), data={"condition_seconds": "2.0"})

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {"id": "job-018", "status": "queued", "progress": 0}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=status_resp)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_cm):
            with TestClient(server.app) as client:
                resp = client.get("/jobs/job-018")

        assert resp.json()["condition_frames"] == 49
        assert resp.json()["generated_frames"] == 140
