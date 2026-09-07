"""STORY_026: trim_prefix / has_audio / _finalise_output without a real render."""

from __future__ import annotations

import subprocess
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
