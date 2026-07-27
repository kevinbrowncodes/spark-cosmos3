"""Unit/contract tests for V2V mode dispatch (STORY_017).

Covers: exactly-one-of image/video, mode reporting on /generate and /jobs,
the 4k+1 frame rule on the V2V path, the forced prose path until STORY_019,
and a regression guard that the I2V path forwards exactly what it did before.
"""

import json
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

from tests.helpers import make_clip

_SMALL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
# Since STORY_018 the gateway decodes the clip, so this must be a real one.
# Exactly 5 frames — the default conditioning window — so prepare_tail returns
# it byte-identical and the forwarding assertions below stay meaningful.
_CLIP = make_clip(5)


def _post(files, data=None, upsample_result=None):
    """Drive POST /generate with the engine + upsampler mocked.

    Returns (response, captured) where captured holds the multipart form and
    files the gateway forwarded to vLLM-Omni.
    """
    if upsample_result is None:
        upsample_result = ('{"subjects": []}', None, {"reasoner": "opus"})

    captured = {}
    cosmos_resp = MagicMock()
    cosmos_resp.status_code = 200
    cosmos_resp.json.return_value = {"id": "job-017", "status": "queued", "progress": 0}

    async def engine_post(url, data=None, files=None, **kw):
        captured["data"] = data
        captured["files"] = files
        return cosmos_resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=engine_post)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    payload = {"prompt": "a cat knocks a glass off a table"}
    payload.update(data or {})

    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=AsyncMock(return_value=upsample_result)),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            resp = client.post("/generate", data=payload, files=files)
    return resp, captured


_IMAGE = {"image": ("t.png", _SMALL_PNG, "image/png")}
_VIDEO = {"video": ("clip.mp4", _CLIP, "video/mp4")}


class TestModeDispatch:
    def test_image_only_is_i2v(self):
        resp, captured = _post(_IMAGE)
        assert resp.status_code == 200
        assert resp.json()["mode"] == "i2v"
        name, body, media_type = captured["files"]["input_reference"]
        assert (name, body, media_type) == ("t.png", _SMALL_PNG, "image/png")

    def test_video_only_is_v2v(self):
        resp, captured = _post(_VIDEO, data={"upsample": "false"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "v2v"
        name, body, media_type = captured["files"]["input_reference"]
        assert (name, body, media_type) == ("clip.mp4", _CLIP, "video/mp4")

    def test_both_supplied_is_400(self):
        resp, _ = _post({**_IMAGE, **_VIDEO})
        assert resp.status_code == 400
        assert "both were supplied" in resp.json()["detail"]

    def test_neither_supplied_is_400(self):
        resp, _ = _post({})
        assert resp.status_code == 400
        assert "neither was supplied" in resp.json()["detail"]

    def test_video_without_declared_type_defaults_to_mp4(self):
        resp, captured = _post(
            {"video": ("clip.mp4", _CLIP)}, data={"upsample": "false"}
        )
        assert resp.status_code == 200
        assert captured["files"]["input_reference"][2] == "video/mp4"


class TestFrameCountRule:
    """4k+1 — the VAE folds 4 pixel frames into 1 latent frame."""

    def test_valid_counts_accepted(self):
        # 4k+1 *and* leaving a generated span inside the vendored schema's
        # 2s-10s range. Since STORY_020 duration is measured over generated
        # frames, so the default 5-frame window is subtracted first: 49 total
        # would leave only 44 generated (1.8s) and is now correctly rejected.
        for frames in (121, 189, 237):
            resp, _ = _post(_VIDEO, data={"frames": str(frames), "upsample": "false"})
            assert resp.status_code == 200, f"{frames} should be valid"

    def test_289_frames_needs_the_matching_conditioning_window(self):
        # 289 is the epic's target, but only with condition_seconds=2.0:
        # 289 - 49 = 240 generated = exactly 10s. With the default 5-frame
        # window it leaves 284 generated (11.8s), still outside the schema.
        resp, _ = _post(_VIDEO, data={"frames": "289", "upsample": "false"})
        assert resp.status_code == 400
        assert "4k+1" not in resp.json()["detail"]

    def test_invalid_counts_rejected(self):
        for frames in (190, 200, 240):
            resp, _ = _post(_VIDEO, data={"frames": str(frames), "upsample": "false"})
            assert resp.status_code == 400, f"{frames} should be rejected"
            assert "4k+1" in resp.json()["detail"]

    def test_message_names_nearest_valid_counts(self):
        resp, _ = _post(_VIDEO, data={"frames": "200", "upsample": "false"})
        detail = resp.json()["detail"]
        assert "197" in detail and "201" in detail

    def test_i2v_path_is_not_subject_to_the_rule(self):
        # Deliberate: the same latent maths governs I2V, but no I2V request has
        # ever been rejected for it and STORY_017 must not change that path.
        resp, _ = _post(_IMAGE, data={"frames": "240"})
        assert resp.status_code == 200


class TestUpsamplerOnV2V:
    # STORY_017 forced upsample off on V2V and reported
    # "v2v_not_supported"; STORY_019 removed that by vendoring the
    # continuation template. The V2V upsampler contract is covered in
    # test_v2v_upsampler.py — this only guards the I2V path here.

    def test_i2v_still_upsamples(self):
        resp, _ = _post(_IMAGE, data={"upsample": "true"})
        assert resp.json()["prompt_source"] == "upsampled"


class TestI2VRegression:
    """Existing pipeline clients must see no change beyond the added `mode`."""

    _BASELINE_KEYS = {
        "id", "status", "progress", "prompt_source",
        "upsample_fallback_reason", "upsampler_output",
    }
    # Fields added by this epic. Anything outside this set is an unintended
    # change to a response existing clients already parse.
    _ADDED_KEYS = {"mode", "condition_frames", "generated_frames"}

    def test_response_gains_only_known_fields(self):
        resp, _ = _post(_IMAGE)
        assert set(resp.json()) - self._BASELINE_KEYS == self._ADDED_KEYS

    def test_forwarded_form_is_unchanged(self):
        _, captured = _post(_IMAGE)
        form = captured["data"]
        assert form["num_frames"] == "189"
        assert form["num_inference_steps"] == "35"
        assert form["generate_sound"] == "true"
        assert form["sound_duration"] == str(189 / 24)
        assert form["guidance_scale"] == "6.0"
        assert form["flow_shift"] == "10.0"
        assert form["fps"] == "24"
        assert form["max_sequence_length"] == "4096"
        assert json.loads(form["extra_params"]) == {
            "guardrails": False,
            "use_resolution_template": False,
            "use_duration_template": False,
        }

    def test_v2v_forwards_the_same_house_contract(self):
        _, captured = _post(_VIDEO, data={"upsample": "false"})
        form = captured["data"]
        # STORY_017 keeps data/neg.json on both paths so only one variable
        # changes; see the story's negative-prompt note.
        assert form["negative_prompt"] == server._read_data("neg.json")
        assert form["flow_shift"] == "10.0"


class TestJobStatusEcho:
    def test_jobs_endpoint_echoes_mode(self):
        _post(_VIDEO, data={"upsample": "false"})

        status_resp = MagicMock()
        status_resp.status_code = 200
        status_resp.json.return_value = {"id": "job-017", "status": "queued", "progress": 0}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=status_resp)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_cm):
            with TestClient(server.app) as client:
                resp = client.get("/jobs/job-017")

        assert resp.status_code == 200
        assert resp.json()["mode"] == "v2v"
