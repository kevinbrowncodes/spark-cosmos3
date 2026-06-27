"""Unit tests for image helpers and _extract_json (STORY_006)."""

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import upsampler

# Minimal magic-byte headers for each type
_JPEG = b"\xff\xd8" + b"\x00" * 10
_PNG = b"\x89PNG" + b"\x00" * 10
_WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4
_UNKNOWN = b"\x00\x01\x02\x03"


class TestDetectMediaType:
    def test_jpeg(self):
        assert upsampler._detect_media_type(_JPEG) == "image/jpeg"

    def test_png(self):
        assert upsampler._detect_media_type(_PNG) == "image/png"

    def test_webp(self):
        assert upsampler._detect_media_type(_WEBP) == "image/webp"

    def test_unknown_falls_back_to_jpeg(self):
        assert upsampler._detect_media_type(_UNKNOWN) == "image/jpeg"


class TestImageBlock:
    def test_structure(self):
        block = upsampler._image_block(_PNG)
        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"

    def test_data_is_base64_of_input(self):
        import base64
        block = upsampler._image_block(_JPEG)
        decoded = base64.standard_b64decode(block["source"]["data"])
        assert decoded == _JPEG

    def test_media_type_detected_from_bytes_not_hardcoded(self):
        assert upsampler._image_block(_PNG)["source"]["media_type"] == "image/png"
        assert upsampler._image_block(_JPEG)["source"]["media_type"] == "image/jpeg"
        assert upsampler._image_block(_WEBP)["source"]["media_type"] == "image/webp"


class TestExtractJson:
    def test_parses_fenced_json(self):
        text = '```json\n{"key": "value"}\n```'
        assert upsampler._extract_json(text) == {"key": "value"}

    def test_parses_unfenced_json(self):
        text = '  {"key": "value"}  '
        assert upsampler._extract_json(text) == {"key": "value"}

    def test_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            upsampler._extract_json("```json\nnot valid json\n```")

    def test_raises_on_non_dict(self):
        with pytest.raises(ValueError, match="expected dict"):
            upsampler._extract_json("```json\n[1, 2, 3]\n```")

    def test_raises_on_empty_fence(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            upsampler._extract_json("```json\n\n```")
