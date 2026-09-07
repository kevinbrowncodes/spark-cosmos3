"""STORY_030 unit tests: the run store, labels, the memory gate, parse_single."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from flow.agent import PlanError, parse_single
from flow.runs import DEFAULT_VALUES, Executor, RunStore, mem_available_gib, new_run_id, step_label

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"


def test_new_run_id_shape():
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50 and all(i.startswith("run_") and len(i) == 16 for i in ids)


def test_mem_available_gib(tmp_path):
    (tmp_path / "meminfo").write_text("MemTotal:  127000000 kB\nMemAvailable:   25165824 kB\nSwapFree: 1 kB\n")
    assert mem_available_gib(tmp_path / "meminfo") == 24.0
    (tmp_path / "nomem").write_text("MemTotal: 1 kB\n")
    assert mem_available_gib(tmp_path / "nomem") is None
    assert mem_available_gib(tmp_path / "missing") is None


@pytest.mark.parametrize("run, label", [
    ({"state": "planning", "count": 6, "clip_index": 0}, "Writing 6 scripts…"),
    ({"state": "planning", "count": 1, "clip_index": 0}, "Writing 1 script…"),
    ({"state": "review", "count": 3, "clip_index": 0}, "Waiting for review"),
    ({"state": "queued", "count": 3, "clip_index": 0}, "Queued clip 1 of 3"),
    ({"state": "queued", "count": 3, "clip_index": 1}, "Queued clip 2 of 3"),        # between clips
    ({"state": "queued", "count": 3, "clip_index": 2, "error": None}, "Queued clip 3 of 3"),  # after resume (BUG_009)
    ({"state": "rendering", "count": 3, "clip_index": 1}, "Rendering clip 2 of 3"),
    ({"state": "paused", "count": 3, "clip_index": 1, "error": "22 GiB available, need 30"}, "Paused: 22 GiB available, need 30"),
    ({"state": "paused", "count": 3, "clip_index": 1}, "Paused: gate"),
    ({"state": "failed", "count": 3, "clip_index": 2, "error": "cuda oom"}, "Failed at clip 3: cuda oom"),
    ({"state": "failed", "count": 3, "clip_index": 2}, "Failed at clip 3: unknown"),
    ({"state": "done", "count": 3, "clip_index": 3}, "Done"),
])
def test_step_label(run, label):
    assert step_label(run) == label


def test_run_store_roundtrip_ordering_and_atomicity(tmp_path):
    store = RunStore(tmp_path / "runs")
    a = store.save({"id": "run_a", "state": "done", "count": 1, "clip_index": 1, "created_at": 1.0, "project_id": "p1"})
    b = store.save({"id": "run_b", "state": "review", "count": 2, "clip_index": 0, "created_at": 2.0, "project_id": "p2"})
    assert a["step"] == "Done" and b["step"] == "Waiting for review" and "updated_at" in a
    assert [r["id"] for r in store.list()] == ["run_b", "run_a"]                       # newest first
    assert [r["id"] for r in store.list("p1")] == ["run_a"]
    assert store.load("run_a")["state"] == "done" and store.load("nope") is None
    assert not list((tmp_path / "runs").glob("*.tmp"))                                # atomic: no leftovers
    assert json.loads(store.path("run_b").read_text())["id"] == "run_b"


def test_default_values_protect_the_box():
    assert DEFAULT_VALUES["size"] == "832x480" and DEFAULT_VALUES["length"] == 10 and DEFAULT_VALUES["upsample"] is True


# --- parse_single -----------------------------------------------------------------------

def test_parse_single():
    assert parse_single("<<<SCRIPT 2>>>\n new two \n<<<END SCRIPT>>>", 2) == "new two"
    assert parse_single("plain rewrite <<<TITLES>>>x<<<END TITLES>>>", 2) == "plain rewrite"
    with pytest.raises(PlanError, match=r"got \[3\]"):
        parse_single("<<<SCRIPT 3>>>x<<<END SCRIPT>>>", 2)
    with pytest.raises(PlanError, match="exactly one"):
        parse_single("<<<SCRIPT 1>>>a<<<END SCRIPT>>><<<SCRIPT 2>>>b<<<END SCRIPT>>>", 2)
    with pytest.raises(PlanError, match="empty"):
        parse_single("<<<SCRIPT 2>>>  <<<END SCRIPT>>>", 2)
    with pytest.raises(PlanError, match="empty rewrite"):
        parse_single("   ", 2)


# --- executor loop -----------------------------------------------------------------------

def test_run_forever_survives_a_failing_tick(tmp_path):
    class Fake(Executor):
        def __init__(self):
            self.calls = 0
            self.done = asyncio.Event()

        async def tick(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            if self.calls >= 3:
                self.done.set()

    async def main():
        ex = Fake()
        task = asyncio.create_task(ex.run_forever(0))
        await asyncio.wait_for(ex.done.wait(), timeout=5)
        task.cancel()
        return ex.calls

    assert asyncio.run(main()) >= 3
