"""Unit tests for _parse_size and _pin_output_params (STORY_007)."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import upsampler


class TestParseSize:
    def test_canonical_vertical(self):
        assert upsampler._parse_size("720x1280", 189, 24) == ("720", "9,16", "7s")

    def test_canonical_landscape(self):
        assert upsampler._parse_size("1280x720", 168, 24) == ("720", "16,9", "7s")

    def test_duration_derived_correctly(self):
        _, _, duration = upsampler._parse_size("720x1280", 120, 24)
        assert duration == "5s"

    def test_unsupported_size_raises(self):
        with pytest.raises(ValueError, match="not in RESOLUTION_RATIO_DICT"):
            upsampler._parse_size("1920x1080", 100, 24)

    def test_malformed_size_raises(self):
        with pytest.raises(ValueError):
            upsampler._parse_size("720p", 100, 24)

    def test_duration_out_of_range_raises(self):
        # 300 frames @ 24 fps → "12s", outside '2s'..'10s'
        with pytest.raises(ValueError, match="outside the schema"):
            upsampler._parse_size("720x1280", 300, 24)

    def test_max_valid_duration(self):
        # 240 frames @ 24 fps → "10s" — exactly at the boundary
        _, _, duration = upsampler._parse_size("720x1280", 240, 24)
        assert duration == "10s"

    def test_min_valid_duration(self):
        # 48 frames @ 24 fps → "2s" — minimum
        _, _, duration = upsampler._parse_size("720x1280", 48, 24)
        assert duration == "2s"


class TestPinOutputParams:
    def test_sets_resolution_from_rrd(self):
        data = {}
        upsampler._pin_output_params(data, resolution="720", aspect_ratio="9,16",
                                      duration="7s", fps=24)
        assert data["resolution"] == {"H": 1280, "W": 720}

    def test_h_before_w(self):
        data = {}
        upsampler._pin_output_params(data, resolution="720", aspect_ratio="9,16",
                                      duration="7s", fps=24)
        keys = list(data["resolution"].keys())
        assert keys.index("H") < keys.index("W")

    def test_sets_aspect_ratio(self):
        data = {}
        upsampler._pin_output_params(data, resolution="720", aspect_ratio="9,16",
                                      duration="7s", fps=24)
        assert data["aspect_ratio"] == "9,16"

    def test_sets_duration(self):
        data = {}
        upsampler._pin_output_params(data, resolution="720", aspect_ratio="9,16",
                                      duration="7s", fps=24)
        assert data["duration"] == "7s"

    def test_sets_fps(self):
        data = {}
        upsampler._pin_output_params(data, resolution="720", aspect_ratio="9,16",
                                      duration="7s", fps=24)
        assert data["fps"] == 24

    def test_overwrites_existing_values(self):
        data = {"resolution": "wrong", "aspect_ratio": "wrong", "duration": "wrong", "fps": 0}
        upsampler._pin_output_params(data, resolution="720", aspect_ratio="16,9",
                                      duration="5s", fps=24)
        assert data["resolution"] == {"H": 720, "W": 1280}
        assert data["aspect_ratio"] == "16,9"
        assert data["duration"] == "5s"
        assert data["fps"] == 24


class TestUpsampleInvalidSize:
    def test_returns_invalid_size_reason(self):
        import asyncio

        async def run():
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
                result, reason, meta = await upsampler.upsample(
                    prompt="test",
                    image_bytes=b"\xff\xd8\x00",
                    size="1920x1080",  # not in RRD
                    num_frames=100,
                    fps=24,
                    generate_sound=True,
                )
            assert result is None
            assert reason == "invalid_size"
            assert meta is None

        asyncio.run(run())
