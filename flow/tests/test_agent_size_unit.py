"""STORY_033: the agent takes the clip's shape from the seed and its resolution from the request.

BUG_012 is the case these exist for — a landscape photo asked for at 720x1280 must come back
as 1280x720, not as a squashed portrait, and it must not quietly become a cheaper render.
"""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

import flow.runs as fr
from flow.runs import DEFAULT_TIER, probe_dimensions, size_for_seed, size_options

# What the gateway offers on this box: five shapes, both ways up.
OPTIONS = ["960x960", "1104x832", "832x1104", "1280x720", "720x1280", "640x640", "736x544", "544x736", "832x480", "480x832"]


@pytest.mark.parametrize("requested, seed, expected, why", [
    ("720x1280", (1376, 768), "1280x720", "BUG_012: the Flow UI's portrait default, a landscape photo"),
    ("832x480", (768, 1376), "480x832", "BUG_012: the agent's landscape constant, a portrait photo"),
    ("720x1280", (768, 1376), "720x1280", "already agreeing — left alone"),
    ("832x480", (1376, 768), "832x480", "already agreeing — left alone"),
    ("832x480", (1000, 1000), "640x640", "a square photo picks the square size at that tier"),
    ("960x960", (1000, 1000), "960x960", "a square photo at the larger tier stays there"),
    ("720x1280", (1024, 768), "1104x832", "4:3 landscape keeps its shape and its 720-ish budget"),
    ("832x480", (768, 1024), "544x736", "4:3 portrait at the cheap tier"),
])
def test_shape_from_the_seed_resolution_from_the_request(requested, seed, expected, why):
    assert size_for_seed(OPTIONS, requested, seed) == expected, why


def test_the_tier_is_held_in_both_directions():
    """A 720p request stays 720p and a 480p request stays 480p, whichever way the seed points."""
    assert size_for_seed(OPTIONS, "720x1280", (1376, 768)) == "1280x720"      # 921,600 px either way
    assert size_for_seed(OPTIONS, "480x832", (1376, 768)) == "832x480"        # 399,360 px either way


def test_a_shape_with_no_close_match_picks_the_nearest_rather_than_failing():
    assert size_for_seed(OPTIONS, "832x480", (4000, 500)) == "832x480"        # extreme letterbox
    assert size_for_seed(OPTIONS, "832x480", (500, 4000)) == "480x832"


@pytest.mark.parametrize("requested, seed", [("832x480", None), (None, None)])
def test_an_unmeasurable_seed_leaves_the_request_alone(requested, seed):
    assert size_for_seed(OPTIONS, requested, seed) == requested


def test_no_options_leaves_the_request_alone():
    assert size_for_seed([], "832x480", (1376, 768)) == "832x480"
    assert size_for_seed(["nonsense", "12x"], "832x480", (1376, 768)) == "832x480"


def test_a_missing_request_still_gets_a_shaped_size():
    """With nothing requested the budget is 0, so the smallest matching shape wins — a size
    is still chosen rather than None, because the seed is what matters."""
    assert size_for_seed(OPTIONS, None, (1376, 768)) == "832x480"


def test_the_agent_no_longer_carries_a_hardcoded_size():
    assert "size" not in fr.DEFAULT_VALUES
    assert DEFAULT_TIER == "832x480"        # a pixel budget now, not an orientation


# --- measuring the seed ---------------------------------------------------------------------

def test_probe_dimensions_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(fr.shutil, "which", lambda name: None)
    assert probe_dimensions(tmp_path / "x.png") is None


@pytest.mark.parametrize("stdout", [b"", b"garbage\n", b"0,0\n", b"1376,\n"])
def test_probe_dimensions_survives_unusable_output(tmp_path, monkeypatch, stdout):
    monkeypatch.setattr(fr.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout=stdout))
    assert probe_dimensions(tmp_path / "x.png") is None


def test_probe_dimensions_parses_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(fr.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout=b"1376,768\n"))
    assert probe_dimensions(tmp_path / "x.png") == (1376, 768)


def test_probe_dimensions_survives_a_timeout(tmp_path, monkeypatch):
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 60)
    monkeypatch.setattr(fr.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(subprocess, "run", boom)
    assert probe_dimensions(tmp_path / "x.png") is None


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs real ffmpeg")
def test_probe_dimensions_on_a_real_file(tmp_path):
    """The whole point is measuring a real photo, so measure one — and a video too, since an
    Extend run seeds from a clip."""
    png = tmp_path / "landscape.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=1:size=1376x768:rate=1", "-frames:v", "1", str(png)], check=True)
    assert probe_dimensions(png) == (1376, 768)
    mp4 = tmp_path / "portrait.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=1:size=480x832:rate=24", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    assert probe_dimensions(mp4) == (480, 832)
    assert size_for_seed(OPTIONS, "720x1280", probe_dimensions(png)) == "1280x720"


# --- reading the gateway's offer -------------------------------------------------------------

def test_size_options_reads_the_video_mode(tmp_path):
    from flow.gateway import Cosmos3Gateway
    caps = Cosmos3Gateway(media_dir=tmp_path, sizes=["720x1280", "832x480"]).capabilities()
    assert size_options(caps) == ["720x1280", "832x480"]
    assert size_options(caps, mode="nope") == []


def test_size_options_when_the_gateway_says_nothing():
    assert size_options(object()) == []
