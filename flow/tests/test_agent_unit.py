"""STORY_029 unit tests: the skill library, prompt rendering, and the parser."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from flow.agent import (
    COUNT_TOKEN,
    KEEP_ALIVE,
    NUM_CTX,
    Instruction,
    PlanError,
    Planner,
    first_sentence,
    load_instructions,
    parse_plan,
    render_prompt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"


# --- library -------------------------------------------------------------------------

def test_load_instructions_reads_frontmatter_and_locks_count():
    by_id = {i.id: i for i in load_instructions(FIXTURES)}
    assert set(by_id) == {"scene-skill", "single-skill", "bare"}          # notes.txt ignored
    scene = by_id["scene-skill"]
    assert scene.description == "A tiny test skill that writes {{COUNT}} scripts."   # first sentence only
    assert scene.count_locked is False and COUNT_TOKEN in scene.body
    assert by_id["single-skill"].count_locked is True
    bare = by_id["bare"]
    assert bare.name == "bare" and bare.description == "" and bare.count_locked is False
    assert "No frontmatter here" in bare.body


def test_load_instructions_is_live_and_skips_readme(tmp_path):
    assert load_instructions(tmp_path / "missing") == []
    (tmp_path / "README.md").write_text("# not a skill")
    assert load_instructions(tmp_path) == []
    shutil.copy(FIXTURES / "single-skill.md", tmp_path / "single-skill.md")
    assert [i.id for i in load_instructions(tmp_path)] == ["single-skill"]
    (tmp_path / "zz.md").write_text("---\nname: aa-first\ndescription: 'Quoted. More.'\n---\nbody {{COUNT}}\n")
    ids = [i.id for i in load_instructions(tmp_path)]
    assert ids == ["aa-first", "single-skill"]                              # sorted by id, not filename
    assert load_instructions(tmp_path)[0].description == "Quoted."


def test_frontmatter_edge_cases(tmp_path):
    (tmp_path / "open.md").write_text("---\nname: open\nno closing fence {{COUNT}}")
    (tmp_path / "block.md").write_text("---\nname: block\ndescription: |\n  Literal block\n  continues\n---\nbody\n")
    by_id = {i.id: i for i in load_instructions(tmp_path)}
    assert by_id["open"].body.startswith("---")                            # unterminated → whole file is body
    assert by_id["block"].description == "Literal block continues"


@pytest.mark.parametrize("text, expected", [
    ("One. Two.", "One."),
    ("No terminator here", "No terminator here"),
    ("  spaced\n  out?  next", "spaced out?"),
    ("x" * 300, "x" * 239 + "…"),
])
def test_first_sentence(text, expected):
    assert first_sentence(text) == expected


def test_render_prompt_replaces_every_count():
    scene = next(i for i in load_instructions(FIXTURES) if i.id == "scene-skill")
    out = render_prompt(scene, 6)
    assert COUNT_TOKEN not in out and out.count("6") >= 2


# --- parser ----------------------------------------------------------------------------

BLOCKS = "chatter before\n<<<SCRIPT 1>>>\n one \n<<<END SCRIPT>>>\n<<<SCRIPT 2>>>\ntwo\n<<<END SCRIPT>>>\n<<<SCRIPT 3>>>\nthree\n<<<END SCRIPT>>>\n"
TAIL = "<<<TITLES>>>\n🔥 A\n\n💪 B\n<<<END TITLES>>>\n<<<SUMMARY>>>\n# Piece\n| a | b |\n<<<END SUMMARY>>>\ntrailing chatter"


def test_parse_exact_count_with_titles_and_summary():
    plan = parse_plan(BLOCKS + TAIL, 3)
    assert plan["scripts"] == ["one", "two", "three"]
    assert plan["titles"] == ["🔥 A", "💪 B"]
    assert plan["summary"].startswith("# Piece")


def test_parse_without_titles_or_summary():
    plan = parse_plan(BLOCKS, 3)
    assert plan["titles"] == [] and plan["summary"] is None


@pytest.mark.parametrize("count, msg", [(6, "expected 6 scripts, got 3"), (1, "expected 1 scripts, got 3")])
def test_parse_wrong_count(count, msg):
    with pytest.raises(PlanError, match=msg):
        parse_plan(BLOCKS, count)


def test_parse_rejects_bad_numbering_and_empty_blocks():
    with pytest.raises(PlanError, match=r"numbered \[2, 1\]"):
        parse_plan("<<<SCRIPT 2>>>b<<<END SCRIPT>>><<<SCRIPT 1>>>a<<<END SCRIPT>>>", 2)
    with pytest.raises(PlanError, match="empty"):
        parse_plan("<<<SCRIPT 1>>>   <<<END SCRIPT>>>", 1)


def test_parse_markerless_single_script():
    # Titles/summary blocks are stripped out of a marker-less reply; the rest is the script.
    tail = TAIL.replace("\ntrailing chatter", "")
    plan = parse_plan("Just one paragraph of motion.\n" + tail, 1)
    assert plan["scripts"] == ["Just one paragraph of motion."] and plan["titles"] == ["🔥 A", "💪 B"]
    with pytest.raises(PlanError, match="got 0"):
        parse_plan("Just one paragraph.", 3)
    with pytest.raises(PlanError, match="got 0"):
        parse_plan("   ", 1)


def test_parse_markerless_unterminated_block_is_the_single_script():
    # An unterminated block is not a block; with count 1 the whole text is the script.
    assert parse_plan("<<<SCRIPT 1>>> unterminated motion", 1)["scripts"] == ["<<<SCRIPT 1>>> unterminated motion"]


def test_parse_empty_summary_block_is_none():
    assert parse_plan("<<<SCRIPT 1>>>a<<<END SCRIPT>>><<<SUMMARY>>>   <<<END SUMMARY>>>", 1)["summary"] is None


# --- planner payload ----------------------------------------------------------------------

def test_payload_shape():
    instr = Instruction(id="s", name="s", description="", count_locked=False, body="do {{COUNT}}", path=Path("s.md"))
    body = Planner("http://ollama:11434/", "gemma4:26b").payload(instr, 4, b"\x89PNG")
    assert body["model"] == "gemma4:26b" and body["stream"] is False
    assert body["keep_alive"] == KEEP_ALIVE == 0 and body["options"] == {"num_ctx": NUM_CTX}
    system, user = body["messages"]
    assert system == {"role": "system", "content": "do 4"}
    assert user["role"] == "user" and "COUNT = 4" in user["content"] and user["images"] == ["iVBORw=="]
