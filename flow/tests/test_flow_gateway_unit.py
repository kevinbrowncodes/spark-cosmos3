"""Unit tests for flow/gateway.py — pure helpers and the job mapping (STORY_023)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flow_protocol import GenerateRequest
from flow_protocol.gateway import UpstreamError

from flow.gateway import DEFAULT_SIZES, STATUS, Cosmos3Gateway, _parse_size, sizes_from_resolution_dict

REPO_RRD = Path(__file__).resolve().parents[2] / "data" / "resolution_ratio_dict.json"


def write_rrd(path: Path, tiers: dict) -> Path:
    path.write_text(json.dumps(tiers))
    return path


@pytest.fixture
def gw(tmp_path: Path) -> Cosmos3Gateway:
    return Cosmos3Gateway(base_url="http://fake-gateway:8002", media_dir=tmp_path)


# --- sizes_from_resolution_dict ---------------------------------------------

def test_sizes_walk_the_720_then_480_tier(tmp_path):
    p = write_rrd(tmp_path / "rrd.json", {
        "720": {"9,16": {"W": 720, "H": 1280}, "16,9": {"W": 1280, "H": 720}},
        "480": {"16,9": {"W": 832, "H": 480}},
        "256": {"1,1": {"W": 256, "H": 256}},   # not in the default tiers
    })
    assert sizes_from_resolution_dict(p) == ["720x1280", "1280x720", "832x480"]


def test_sizes_honour_explicit_tiers(tmp_path):
    p = write_rrd(tmp_path / "rrd.json", {"256": {"1,1": {"W": 256, "H": 256}}})
    assert sizes_from_resolution_dict(p, tiers=("256",)) == ["256x256"]


def test_sizes_fall_back_when_no_tier_matches(tmp_path):
    p = write_rrd(tmp_path / "rrd.json", {"1080": {"16,9": {"W": 1920, "H": 1080}}})
    assert sizes_from_resolution_dict(p) == DEFAULT_SIZES


@pytest.mark.skipif(not REPO_RRD.is_file(), reason="repo data/ not present (Docker test stage)")
def test_sizes_from_the_real_resolution_dict():
    sizes = sizes_from_resolution_dict(REPO_RRD)
    assert "720x1280" in sizes and "832x480" in sizes
    assert all(s.count("x") == 1 for s in sizes)


# --- _parse_size / STATUS ----------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [("704x1280", (704, 1280)), ("1280X720", (1280, 720)), (None, (None, None)), ("junk", (None, None)), ("12x", (None, None))],
)
def test_parse_size(raw, expected):
    assert _parse_size(raw) == expected


def test_status_map_covers_every_engine_state():
    assert STATUS["queued"] == "queued"
    assert STATUS["in_progress"] == "running"
    assert STATUS["completed"] == "done"
    assert {STATUS[s] for s in ("failed", "cancelled", "error")} == {"failed"}


# --- construction / capabilities --------------------------------------------

def test_media_roots_are_created(gw, tmp_path):
    assert (tmp_path / "flow-uploads").is_dir()
    assert (tmp_path / "flow-outputs").is_dir()


def test_capabilities_shape(gw):
    caps = gw.capabilities()
    assert caps.protocol == 1 and caps.name == "Cosmos 3 Nano"
    assert caps.reference == "required" and caps.reference_kinds == ["image"]
    assert caps.progress == "percent"
    mode = caps.mode("video")
    assert mode is not None
    assert mode.field("size").default == "720x1280"
    assert mode.field("frames") is None
    length = mode.by_role("duration")
    assert length is not None and length.key == "length" and length.default == 8
    assert [o.value for o in length.options] == [5, 8, 10] and length.options[0].label == "5 s"
    assert [o.value for o in mode.by_role("count").options] == [1]
    assert "one clip at a time" in caps.strings.footer and "does not stop" in caps.strings.footer


def test_capabilities_default_size_falls_back_to_first_option(tmp_path):
    gw = Cosmos3Gateway(media_dir=tmp_path, sizes=["832x480", "640x640"])
    assert gw.capabilities().mode("video").field("size").default == "832x480"


def test_capabilities_sizes_come_from_the_resolution_dict(tmp_path):
    p = write_rrd(tmp_path / "rrd.json", {"720": {"9,16": {"W": 720, "H": 1280}}, "480": {"16,9": {"W": 832, "H": 480}}})
    gw = Cosmos3Gateway(media_dir=tmp_path, resolution_dict=p, name="Test Box")
    field = gw.capabilities().mode("video").field("size")
    assert [o.value for o in field.options] == ["720x1280", "832x480"]
    assert gw.capabilities().name == "Test Box"


# --- _to_job -----------------------------------------------------------------

def test_to_job_completed(gw):
    job = gw._to_job({"id": "v1", "status": "completed", "progress": 100, "size": "704x1280", "seconds": "7.9"})
    assert job.status == "done" and job.media_id == "out:v1.mp4"
    assert (job.width, job.height, job.duration_s, job.progress) == (704, 1280, None, 100.0)
    assert job.error is None


def test_to_job_running_has_no_media_yet(gw):
    job = gw._to_job({"id": "v1", "status": "in_progress", "progress": 42, "size": "704x1280"})
    assert job.status == "running" and job.progress == 42.0 and job.media_id is None


def test_to_job_unknown_status_is_failed(gw):
    assert gw._to_job({"id": "v1", "status": "exploded"}).status == "failed"


def test_to_job_error_forms(gw):
    assert gw._to_job({"id": "v1", "status": "failed", "error": {"message": "cuda oom"}}).error == "cuda oom"
    assert gw._to_job({"id": "v1", "status": "failed", "error": {"code": 7}}).error == '{"code": 7}'
    assert gw._to_job({"id": "v1", "status": "failed", "error": "plain text"}).error == "plain text"


def test_to_job_missing_or_blank_fields(gw):
    job = gw._to_job({"id": "v1", "status": "queued", "seconds": ""})
    assert job.progress is None and job.duration_s is None and (job.width, job.height) == (None, None)


def test_to_job_uses_the_size_and_length_remembered_at_submit(gw):
    gw._meta_by_job["v1"] = {"size": "832x480", "length": 5.0}
    job = gw._to_job({"id": "v1", "status": "queued"})
    assert (job.width, job.height, job.duration_s) == (832, 480, 5.0)


# --- generate guard -----------------------------------------------------------

def test_generate_without_a_stored_reference_is_404(gw):
    req = GenerateRequest(mode="video", prompt="x", values={}, reference_id="in:missing.png")
    with pytest.raises(UpstreamError) as exc:
        gw.generate(req)
    assert exc.value.status == 404


def test_generate_with_no_reference_at_all_is_404(gw):
    with pytest.raises(UpstreamError) as exc:
        gw.generate(GenerateRequest(mode="video", prompt="x", values={}))
    assert exc.value.status == 404
