"""STORY_026: trim_prefix / has_audio / _finalise_output without a real render."""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

import flow.gateway as fg
from flow.gateway import Cosmos3Gateway, has_audio, trim_prefix


@pytest.fixture
def gw(tmp_path):
    return Cosmos3Gateway(base_url="http://fake-gateway:8002", media_dir=tmp_path)


def test_trim_prefix_builds_a_frame_accurate_argv(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"out")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(fg, "has_audio", lambda p: True)
    raw, out = tmp_path / "raw.mp4", tmp_path / "out.mp4"
    raw.write_bytes(b"raw")
    assert trim_prefix(raw, out, 73) == out and out.read_bytes() == b"out"
    argv = calls[0]
    assert argv[argv.index("-vf") + 1] == "select='gte(n,73)',setpts=PTS-STARTPTS"
    assert argv[argv.index("-af") + 1] == "atrim=start=3.0416667,asetpts=PTS-STARTPTS"
    assert argv[-1].endswith("out.part") and "-c:a" in argv and not list(tmp_path.glob("*.part"))
    assert argv[argv.index("-r") + 1] == "24"                       # BUG_007


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs real ffmpeg")
def test_trim_prefix_keeps_exact_24_fps_with_real_ffmpeg(tmp_path):
    """BUG_007: a trimmed clip must be a first-class 24 fps clip — avg_frame_rate
    exactly 24/1 and a duration of nb_frames/24 — or the gateway refuses it as the
    next Extend source. Synthetic 2 s source: 48 frames + a sine track."""
    raw = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(raw)], check=True)
    assert has_audio(raw)
    out = trim_prefix(raw, tmp_path / "out.mp4", 13)
    assert out is not None
    fields = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=avg_frame_rate,duration,nb_frames", "-of", "csv=p=0", str(out)],
                            capture_output=True, text=True, check=True).stdout.strip().split(",")
    rate, duration, frames = fields[0], float(fields[1]), int(fields[2])
    assert Fraction(rate) == 24 and frames == 48 - 13 and abs(duration - frames / 24) < 1e-3


def test_trim_prefix_skips_audio_filters_for_silent_clips(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"o")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(fg, "has_audio", lambda p: False)
    raw = tmp_path / "raw.mp4"; raw.write_bytes(b"raw")
    assert trim_prefix(raw, tmp_path / "out.mp4", 5) is not None
    assert "-af" not in calls[0] and "-c:a" not in calls[0]


def test_trim_prefix_failure_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: SimpleNamespace(returncode=1, stderr=b"boom"))
    monkeypatch.setattr(fg, "has_audio", lambda p: False)
    raw = tmp_path / "raw.mp4"; raw.write_bytes(b"raw")
    assert trim_prefix(raw, tmp_path / "out.mp4", 5) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["raw.mp4"]


def test_trim_prefix_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(fg.shutil, "which", lambda name: None)
    raw = tmp_path / "raw.mp4"; raw.write_bytes(b"raw")
    assert trim_prefix(raw, tmp_path / "out.mp4", 5) is None


def test_has_audio_without_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(fg.shutil, "which", lambda name: None)
    assert has_audio(tmp_path / "x.mp4") is False


def test_has_audio_parses_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(fg.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout=b"audio\n"))
    assert has_audio(tmp_path / "x.mp4") is True


def test_finalise_output_is_a_noop_for_generate(gw, tmp_path):
    p = tmp_path / "flow-outputs" / "g.mp4"; p.write_bytes(b"g")
    gw._meta_by_job["g"] = {"condition_frames": None}
    assert gw._finalise_output("g", p) == p and not gw.raw_dir.exists()


def test_finalise_output_trims_once(gw, tmp_path, monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(fg, "trim_prefix", lambda raw, out, n, fps=24: seen.append(n) or out.write_bytes(b"t") or out)
    p = tmp_path / "flow-outputs" / "e.mp4"; p.write_bytes(b"raw")
    gw._meta_by_job["e"] = {"condition_frames": 73}
    assert gw._finalise_output("e", p).read_bytes() == b"t"
    assert (gw.raw_dir / "e.mp4").read_bytes() == b"raw"
    assert gw._finalise_output("e", p) == p and seen == [73]          # second pass: raw exists → skip


def test_finalise_output_restores_raw_when_trim_fails(gw, tmp_path, monkeypatch):
    monkeypatch.setattr(fg, "trim_prefix", lambda raw, out, n, fps=24: None)
    p = tmp_path / "flow-outputs" / "e.mp4"; p.write_bytes(b"raw")
    gw._meta_by_job["e"] = {"condition_frames": 73}
    assert gw._finalise_output("e", p) == p and p.read_bytes() == b"raw"
    assert not (gw.raw_dir / "e.mp4").exists()
