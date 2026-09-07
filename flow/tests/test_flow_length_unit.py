"""STORY_024: Length → frames maths, and proof that every value the UI can
offer is accepted by the gateway's own validators."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from flow.gateway import CONDITION_FRAMES, DEFAULT_LENGTH, FPS, LENGTHS, Cosmos3Gateway, frames_for, snap4k1

REPO = Path(__file__).resolve().parents[2]
GATEWAY_DIR = REPO / "gateway"


@pytest.mark.parametrize("n, expected", [(1, 1), (121, 121), (122, 125), (123, 125), (124, 125), (125, 125), (192, 193), (240, 241), (313, 313)])
def test_snap4k1(n, expected):
    assert snap4k1(expected) == expected  # fixed point
    assert snap4k1(n) == expected


@pytest.mark.parametrize("length, image_frames, video_frames", [(5, 121, 193), (8, 193, 265), (10, 241, 313)])
def test_frames_for_matches_the_story_table(length, image_frames, video_frames):
    assert frames_for(length, "image") == image_frames
    assert frames_for(length, "video") == video_frames
    assert (video_frames - CONDITION_FRAMES) == round(length * FPS)   # exactly L seconds of new video
    assert (image_frames - 1) % 4 == 0 and (video_frames - 1) % 4 == 0


def test_default_length_is_offered():
    assert DEFAULT_LENGTH in LENGTHS


def _load_gateway_module(name: str):
    """Import gateway/<name>.py the way its own tests do (bare module names)."""
    if str(GATEWAY_DIR) not in sys.path:
        sys.path.insert(0, str(GATEWAY_DIR))
    spec = importlib.util.spec_from_file_location(name, GATEWAY_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not (GATEWAY_DIR / "upsampler.py").is_file(), reason="gateway/ not present (Docker test stage)")
def test_every_ui_value_passes_the_gateway_validators(tmp_path):
    """The contract this story exists for: no UI click can produce a gateway 400
    for size/length/steps. Uses the gateway's real validators, not a copy."""
    upsampler = _load_gateway_module("upsampler")
    server = _load_gateway_module("server")
    sizes = Cosmos3Gateway(media_dir=tmp_path, resolution_dict=REPO / "data" / "resolution_ratio_dict.json").sizes
    assert sizes, "no sizes from the resolution dict"
    for size in sizes:
        ceiling = server._frame_ceiling(size)
        for length in LENGTHS:
            image_frames = frames_for(length, "image")
            assert image_frames <= ceiling, (size, length, image_frames, ceiling)
            upsampler._parse_size(size, image_frames, FPS)                       # raises ValueError on a bad duration
            video_frames = frames_for(length, "video")
            assert video_frames <= max(ceiling, 313), (size, length, video_frames)
            assert server._is_valid_frame_count(video_frames)
            upsampler._parse_size(size, video_frames, FPS, CONDITION_FRAMES)


# --- duration precedence -----------------------------------------------------------

@pytest.fixture
def gw(tmp_path):
    return Cosmos3Gateway(base_url="http://fake-gateway:8002", media_dir=tmp_path)


def test_duration_prefers_the_remembered_length(gw):
    gw._meta_by_job["v1"] = {"size": "704x1280", "length": 8.0}
    job = gw._to_job({"id": "v1", "status": "completed", "seconds": "4", "generated_frames": 240})
    assert job.duration_s == 8.0 and (job.width, job.height) == (704, 1280)


def test_duration_falls_back_to_generated_frames(gw):
    assert gw._to_job({"id": "v1", "status": "completed", "generated_frames": 240}).duration_s == 10.0


def test_duration_never_comes_from_seconds(gw):
    job = gw._to_job({"id": "v1", "status": "completed", "seconds": "4", "generated_frames": None})
    assert job.duration_s is None
