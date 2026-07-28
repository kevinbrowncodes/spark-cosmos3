"""Unit/contract tests for the V2V upsampler contract (STORY_019).

Covers: template selection by mode, continuation-not-description framing,
duration measured from generated frames, frame sampling from the conditioning
window, and that the I2V prompt is byte-identical to before.
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
import video as video_util

from tests.helpers import make_clip

_SMALL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
_STRUCTURED = json.dumps({"subjects": [{"name": "car"}], "audio_description": "gravel"})


class TestTemplateSelection:
    _KW = dict(resolution="480", aspect_ratio="16,9", duration="5s", fps=24)

    def test_i2v_prompt_is_unchanged(self):
        # Regression guard: the default must still produce exactly the I2V text.
        text = upsampler.build_upsampler_prompt("a car drives", **self._KW)
        assert upsampler.I2V_INTRO in text
        assert upsampler.I2V_IMAGE_NOTE in text
        assert upsampler.V2V_VIDEO_NOTE not in text

    def test_v2v_prompt_swaps_both_slots(self):
        text = upsampler.build_upsampler_prompt("a car drives", mode="v2v", **self._KW)
        assert upsampler.V2V_INTRO in text
        assert upsampler.V2V_VIDEO_NOTE in text
        assert upsampler.I2V_IMAGE_NOTE not in text

    def test_v2v_note_states_continuation_not_retelling(self):
        note = upsampler.V2V_VIDEO_NOTE
        assert "continuation, not a retelling" in note
        assert note.index("temporal_caption") < note.index("audio_description")
        assert "Do NOT re-narrate" in note

    def test_v2v_note_does_not_request_fields_outside_the_schema(self):
        # The report's Appendix B.1 template has scene_imagination; the vendored
        # cosmos-framework schema does not. Asking for it made Gemma emit a key
        # the template forbids, which strict validation then rejected.
        schema = (_REPO_ROOT / "data" / "upsampler_schema.json").read_text()
        assert "scene_imagination" not in schema
        note = upsampler.V2V_VIDEO_NOTE
        assert "Write scene_imagination" not in note
        assert "no scene_imagination field" in note  # explicitly warned against


class TestDurationFromGeneratedFrames:
    """`duration` describes the continuation, not the whole output."""

    @staticmethod
    async def _capture(mode, num_frames, condition_frames):
        seen = {}

        async def fake_opus(user_text, images, *a, **kw):
            seen["text"] = user_text
            seen["images"] = images
            return _STRUCTURED, None, {"reasoner": "opus"}

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}),
            patch("upsampler._upsample_opus", new=fake_opus),
        ):
            await upsampler.upsample(
                prompt="p", image_bytes=b"x", size="832x480", num_frames=num_frames,
                fps=24, generate_sound=True, mode=mode, condition_frames=condition_frames,
            )
        return seen["text"]

    @pytest.mark.asyncio
    async def test_v2v_duration_excludes_the_conditioning_window(self):
        # 189 total - 49 conditioning = 140 generated = 5.83 s -> '5s'
        text = await self._capture("v2v", 189, 49)
        assert "duration 5s" in text

    @pytest.mark.asyncio
    async def test_i2v_duration_uses_total_frames(self):
        text = await self._capture("i2v", 189, 0)
        assert "duration 7s" in text

    @pytest.mark.asyncio
    async def test_the_target_config_lands_on_ten_seconds(self):
        # The epic's goal: 289 total - 49 conditioning = 240 = exactly 10 s,
        # the top of the vendored schema's range. STORY_020 makes the gateway's
        # own validation agree; here the upsampler already computes it.
        text = await self._capture("v2v", 289, 49)
        assert "duration 10s" in text


class TestFrameSampling:
    def test_samples_are_jpegs_in_order(self):
        clip = make_clip(49)
        stills = video_util.sample_frames(clip, 5)
        assert len(stills) == 5
        assert all(s[:2] == b"\xff\xd8" for s in stills), "not JPEG"

    def test_last_frame_is_always_included(self):
        # The continuation starts there — it is the most important still.
        clip = make_clip(49)
        stills = video_util.sample_frames(clip, 5)
        last_alone = video_util.sample_frames(clip, 1)
        assert len(stills[-1]) > 0 and len(last_alone) == 1

    def test_more_samples_than_frames_returns_every_frame(self):
        assert len(video_util.sample_frames(make_clip(3), 10)) == 3

    def test_zero_count_rejected(self):
        with pytest.raises(video_util.ClipError):
            video_util.sample_frames(make_clip(5), 0)


def _post(files, data=None, upsample_result=None):
    if upsample_result is None:
        upsample_result = (_STRUCTURED, None, {"reasoner": "opus"})
    captured = {}
    cosmos_resp = MagicMock()
    cosmos_resp.status_code = 200
    cosmos_resp.json.return_value = {"id": "job-019", "status": "queued", "progress": 0}

    async def engine_post(url, data=None, files=None, **kw):
        captured["data"] = data
        return cosmos_resp

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=engine_post)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    up = AsyncMock(return_value=upsample_result)
    payload = {"prompt": "the car pulls away"}
    payload.update(data or {})

    with (
        patch("httpx.AsyncClient", return_value=mock_cm),
        patch("upsampler.upsample", new=up),
        patch("job_logger.write"),
    ):
        with TestClient(server.app) as client:
            resp = client.post("/generate", data=payload, files=files)
    return resp, captured, up


class TestGatewayWiring:
    def test_v2v_now_upsamples(self):
        # The "v2v_not_supported" fallback from STORY_017 is gone.
        resp, captured, _ = _post({"video": ("c.mp4", make_clip(189), "video/mp4")},
                                  data={"condition_seconds": "2.0"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt_source"] == "upsampled"
        assert body["upsample_fallback_reason"] is None
        assert body["upsampler_output"] == _STRUCTURED
        assert captured["data"]["prompt"] == _STRUCTURED

    def test_upsampler_receives_mode_and_condition_frames(self):
        _, _, up = _post({"video": ("c.mp4", make_clip(189), "video/mp4")},
                         data={"condition_seconds": "2.0"})
        kwargs = up.await_args.kwargs
        assert kwargs["mode"] == "v2v"
        assert kwargs["condition_frames"] == 49
        assert isinstance(kwargs["image_bytes"], list)
        assert len(kwargs["image_bytes"]) == server._V2V_PROMPT_FRAMES

    def test_stills_come_from_the_trimmed_window(self):
        # Frame luma encodes source position; the trimmed tail of a 189-frame
        # clip is all bright, so every still must be bright. Stills sampled from
        # the original upload would include dark early frames.
        _, _, up = _post({"video": ("c.mp4", make_clip(189), "video/mp4")},
                         data={"condition_seconds": "2.0"})
        import io
        import av
        for still in up.await_args.kwargs["image_bytes"]:
            with av.open(io.BytesIO(still)) as c:
                frame = next(c.decode(video=0))
                plane = bytes(frame.planes[0])
                assert sum(plane) / len(plane) > 180

    def test_i2v_still_sends_a_single_image(self):
        _, _, up = _post({"image": ("t.png", _SMALL_PNG, "image/png")})
        kwargs = up.await_args.kwargs
        assert kwargs["mode"] == "i2v"
        assert kwargs["image_bytes"] == _SMALL_PNG
        assert kwargs["condition_frames"] == 0

    def test_upsample_false_still_uses_prose(self):
        resp, captured, _ = _post({"video": ("c.mp4", make_clip(189), "video/mp4")},
                                  data={"condition_seconds": "2.0", "upsample": "false"})
        assert resp.json()["prompt_source"] == "prose"
        assert captured["data"]["prompt"] == "the car pulls away"

    def test_upsample_failure_falls_back_to_prose(self):
        resp, captured, _ = _post(
            {"video": ("c.mp4", make_clip(189), "video/mp4")},
            data={"condition_seconds": "2.0"},
            upsample_result=(None, "invalid_json", {"reasoner": "opus"}),
        )
        assert resp.status_code == 200
        assert resp.json()["prompt_source"] == "prose"
        assert resp.json()["upsample_fallback_reason"] == "invalid_json"
        assert captured["data"]["prompt"] == "the car pulls away"


class TestFrameLabels:
    """Ordering must be stated, not inferred from message position (STORY_019 fix)."""

    def test_labels_name_position_and_timestamp(self):
        labels = upsampler.frame_labels(5, 73, 24)
        assert len(labels) == 5
        assert labels[0].startswith("conditioning frame 1 of 5, t=0.00s")
        assert "t=3.00s" in labels[-1]

    def test_last_label_marks_the_continuation_boundary(self):
        labels = upsampler.frame_labels(5, 73, 24)
        assert "final frame before the continuation" in labels[-1]
        assert not any("final frame" in l for l in labels[:-1])

    def test_timestamps_are_monotonic(self):
        times = [float(l.split("t=")[1].split("s")[0]) for l in upsampler.frame_labels(5, 97, 24)]
        assert times == sorted(times)
        assert times[-1] == pytest.approx(96 / 24)

    def test_single_still_still_labelled(self):
        assert len(upsampler.frame_labels(1, 49, 24)) == 1

    def test_no_labels_for_zero_count(self):
        assert upsampler.frame_labels(0, 49, 24) == []

    def test_images_are_interleaved_with_their_labels(self):
        blocks = upsampler._labelled_images([b"\xff\xd8a", b"\xff\xd8b"], ["one", "two"])
        assert [b["type"] for b in blocks] == ["text", "image", "text", "image"]
        assert blocks[0]["text"] == "one" and blocks[2]["text"] == "two"

    def test_unlabelled_images_pass_through(self):
        blocks = upsampler._labelled_images([b"\xff\xd8a"], None)
        assert [b["type"] for b in blocks] == ["image"]

    @pytest.mark.asyncio
    async def test_v2v_sends_labels_and_i2v_does_not(self):
        seen = {}

        async def fake(user_text, images, gs, res, ar, dur, fps, labels=None):
            seen["labels"] = labels
            return _STRUCTURED, None, {"reasoner": "opus"}

        for mode, cond, expect in (("v2v", 49, True), ("i2v", 0, False)):
            with (
                patch.dict(os.environ, {"ANTHROPIC_API_KEY": "t"}),
                patch("upsampler._upsample_opus", new=fake),
            ):
                await upsampler.upsample(
                    prompt="p", image_bytes=[b"\xff\xd8a", b"\xff\xd8b"], size="832x480",
                    num_frames=189, fps=24, generate_sound=True, mode=mode,
                    condition_frames=cond,
                )
            assert bool(seen["labels"]) is expect, f"{mode} label handling wrong"
