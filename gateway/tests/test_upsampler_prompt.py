"""Unit tests for the official NVIDIA template-based prompt assembly (STORY_005)."""

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
os.environ.setdefault("DATA_DIR", str(_REPO_ROOT / "data"))

sys.path.insert(0, str(Path(__file__).parent.parent))

import upsampler

FIXTURES = Path(__file__).parent / "fixtures"
PROMPT_CAR = (
    "A car is driving fast. Rocks start falling from the mountains. "
    "The car makes a sudden stop."
)


class TestBuildUpsamplerPrompt:
    def test_golden_landscape_720_169(self):
        expected = (FIXTURES / "upsampler_prompt_720_169.txt").read_text(encoding="utf-8")
        actual = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="16,9", duration="7s", fps=24
        )
        assert actual == expected, (
            f"Prompt mismatch at first diff:\n"
            f"  expected len={len(expected)}, actual len={len(actual)}\n"
            f"  first 200 chars of expected: {expected[:200]!r}\n"
            f"  first 200 chars of actual:   {actual[:200]!r}"
        )

    def test_golden_vertical_720_916(self):
        expected = (FIXTURES / "upsampler_prompt_720_916.txt").read_text(encoding="utf-8")
        actual = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="9,16", duration="7s", fps=24
        )
        assert actual == expected, (
            f"Prompt mismatch at first diff:\n"
            f"  expected len={len(expected)}, actual len={len(actual)}\n"
            f"  first 200 chars of expected: {expected[:200]!r}\n"
            f"  first 200 chars of actual:   {actual[:200]!r}"
        )

    def test_output_parameters_line_present(self):
        result = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="9,16", duration="7s", fps=24
        )
        assert "Output parameters: resolution 720, aspect_ratio 9,16, duration 7s, fps 24." in result

    def test_i2v_intro_present(self):
        result = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="9,16", duration="7s", fps=24
        )
        assert upsampler.I2V_INTRO in result

    def test_i2v_image_note_present(self):
        result = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="9,16", duration="7s", fps=24
        )
        assert "IMPORTANT - IMAGE INPUT" in result

    def test_schema_embedded(self):
        result = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="9,16", duration="7s", fps=24
        )
        assert upsampler.SCHEMA[:50] in result

    def test_rrd_h_before_w_in_output(self):
        result = upsampler.build_upsampler_prompt(
            PROMPT_CAR, resolution="720", aspect_ratio="9,16", duration="7s", fps=24
        )
        # Framework serialises H first; verify the ordering in the embedded dict
        h_pos = result.find('"H"')
        w_pos = result.find('"W"')
        assert h_pos < w_pos, "H key must appear before W key in embedded resolution dict"
