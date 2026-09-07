"""STORY_028 E2E: drive the projects home page in headless Chromium at the LAN address.

Phase A (default) — no render, ~30 s:
  empty state → New project → the card appears → hover rename/delete → the ⋮ About rows →
  deleting a project leaves the clips on disk and in the asset picker → the page still works
  with `crypto.randomUUID` absent, the sidecar's shim neutralised (v0.2.0 fixed `uuid()`
  upstream, BUG_005) → Delete all.

Phase B — `--phase B --state <storage state>`: the project that rendered a clip shows that
clip as its card thumbnail. Pass the state file that `e2e_ui_generate.py --state` wrote, so
this reads the same browser profile that did the render.

    python3 flow/tests/e2e_ui_home.py --base http://192.168.1.33:8003 --out docs/evidence/story-028-home-page
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# Neutralise the sidecar's shim in the page instead of rewriting the document: fulfilling the
# index makes Chromium treat the bundle's `crossorigin` script and stylesheet as cross-origin
# from a non-secure context and block them, which looks like a broken bundle but is the test's
# own fault. A non-writable undefined property makes the shim's assignment a silent no-op, so
# the page sees exactly what a plain-http browser sees natively.
NEUTRALISE_SHIM = """
Object.defineProperty(globalThis.crypto, 'randomUUID',
  { value: undefined, writable: false, configurable: false });
"""


def clear_projects(page) -> None:
    if page.get_by_test_id("project-card").count():
        page.get_by_role("button", name="More options").click()
        page.get_by_text("Delete all projects", exact=False).click()
        page.get_by_role("dialog", name="Delete all projects?").get_by_role("button", name="Delete all").click()
    expect(page.get_by_test_id("project-card")).to_have_count(0)


def phase_b(browser, ui: str, out: Path, state: Path) -> int:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, storage_state=str(state))
    page = ctx.new_page()
    page.goto(ui)
    page.wait_for_selector("[data-testid=projects-grid]")
    card = page.get_by_test_id("project-card").first
    img = card.locator("img").first
    expect(img).to_be_visible(timeout=30_000)
    src = img.get_attribute("src") or ""
    log("card thumbnail src:", src)
    assert "/flow/media/" in src and "type=THUMBNAIL" in src, src
    ct = page.evaluate("s => fetch(s).then(r => r.headers.get('content-type'))", src)
    log("thumbnail content-type:", ct)
    assert ct and ct.startswith("image/"), ct
    page.screenshot(path=str(out / "09-card-thumbnail-after-render.png"))
    log("PHASE B OK")
    return 0


def phase_a(browser, base: str, ui: str, out: Path, outputs: Path) -> int:
    caps = json.load(urllib.request.urlopen(base + "/flow/capabilities"))
    log("capabilities.agent:", caps.get("agent"))
    assert caps.get("agent"), "the sidecar does not declare the agent capability"

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(ui)
    clear_projects(page)
    expect(page.get_by_text("No projects yet")).to_be_visible()   # matches the editor's empty state
    new_project = page.get_by_role("button", name="New project")
    fixed = new_project.evaluate(
        "b => { let e = b; while (e) { if (getComputedStyle(e).position === 'fixed') return true; e = e.parentElement } return false }")
    log("New project fixed-positioned:", fixed)
    page.screenshot(path=str(out / "01-home-empty.png"))

    new_project.click()
    page.wait_for_selector("[data-testid=composer]")
    log("project url:", page.url)
    page.goto(ui)
    grid = page.get_by_test_id("projects-grid")
    expect(grid).to_be_visible()
    columns = grid.evaluate("g => getComputedStyle(g).gridTemplateColumns.split(' ').length")
    log("grid columns:", columns)
    assert columns == 3, columns
    cards = page.get_by_test_id("project-card")
    expect(cards).to_have_count(1)
    card = cards.first
    page.screenshot(path=str(out / "02-home-one-card.png"))

    card.hover()
    expect(card.get_by_role("button", name="Delete project")).to_be_visible()
    expect(card.get_by_role("button", name="Edit project title")).to_be_visible()
    page.screenshot(path=str(out / "03-card-hover-controls.png"))
    card.get_by_role("button", name="Edit project title").click()
    card.get_by_role("textbox", name="Project title").fill("STORY_028 check")
    card.get_by_role("button", name="Done").click()
    expect(card).to_contain_text("STORY_028 check")
    log("rename OK")

    # The About rows render inside the ⋮ popover, above "Delete all projects…"
    page.get_by_role("button", name="More options").click()
    # the deepest div carrying all four rows — matching one row only ("Flow UI\n0.2.0") is the trap
    about = (page.locator("div")
             .filter(has_text=re.compile(r"Flow UI"))
             .filter(has_text=re.compile(r"Protocol"))
             .filter(has_text=re.compile(r"Model")).last.inner_text())
    log("about:", " | ".join(l for l in about.splitlines() if l.strip())[:300])
    for needle in ("Flow UI", "0.2.0", "Protocol", "v1", "same origin", "Cosmos 3 Nano"):
        assert needle in about, f"About lacks {needle!r}: {about!r}"
    page.screenshot(path=str(out / "04-about.png"))
    page.keyboard.press("Escape")

    before = sorted(f.name for f in outputs.glob("*.mp4"))
    log("clips on disk before delete:", len(before))
    card.hover()
    card.get_by_role("button", name="Delete project").click()
    dialog = page.get_by_role("dialog", name="Delete this project?")
    expect(dialog).to_be_visible()
    page.screenshot(path=str(out / "05-delete-confirm.png"))
    dialog.get_by_role("button", name="Delete project").click()
    expect(page.get_by_test_id("project-card")).to_have_count(0)
    assert sorted(f.name for f in outputs.glob("*.mp4")) == before, "deleting a project touched the clips"

    page.get_by_role("button", name="New project").click()
    page.wait_for_selector("[data-testid=composer]")
    page.get_by_role("button", name="Add assets").click()
    picker = page.get_by_role("dialog", name="Add to Prompt")
    expect(picker.locator("img").first).to_be_visible(timeout=20_000)   # the listing is fetched, not instant
    tiles = picker.locator("img").count()
    listed = picker.inner_text()
    missing = [name for name in before if name not in listed]
    log("asset picker media tiles after the delete:", tiles, "| clips missing from the picker:", missing)
    assert tiles >= len(before) and not missing, (tiles, missing)
    page.screenshot(path=str(out / "06-asset-picker-after-delete.png"))
    assert not errors, errors
    ctx.close()

    # BUG_005: v0.2.0 fixed uuid() upstream, so the page must work with no crypto.randomUUID at all
    ctx2 = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx2.add_init_script(NEUTRALISE_SHIM)
    page2 = ctx2.new_page()
    errors2: list[str] = []
    page2.on("pageerror", lambda e: errors2.append(str(e)))
    page2.goto(ui)
    page2.get_by_role("button", name="New project").wait_for()    # fresh context: its own empty storage
    assert page2.evaluate("typeof globalThis.crypto.randomUUID") == "undefined", "the shim survived neutralisation"
    log("shim neutralised → typeof crypto.randomUUID:", page2.evaluate("typeof globalThis.crypto.randomUUID"),
        "| isSecureContext:", page2.evaluate("window.isSecureContext"))
    page2.get_by_role("button", name="New project").click()
    page2.wait_for_selector("[data-testid=composer]")
    page2.get_by_role("button", name="Add assets").click()
    expect(page2.get_by_role("dialog", name="Add to Prompt")).to_be_visible()
    assert not errors2, errors2
    page2.screenshot(path=str(out / "07-no-randomuuid-new-project-works.png"))

    page2.goto(ui)
    page2.wait_for_selector("[data-testid=projects-grid]")
    clear_projects(page2)
    page2.screenshot(path=str(out / "08-delete-all-clean.png"))
    log("PHASE A OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://192.168.1.33:8003", help="the sidecar, LAN address by default (plain http on purpose)")
    ap.add_argument("--ui-path", default="/flow/")
    ap.add_argument("--out", type=Path, default=Path("docs/evidence/story-028-home-page"))
    ap.add_argument("--outputs", type=Path, default=Path.home() / "Documents/flow-media/flow-outputs")
    ap.add_argument("--phase", choices=["A", "B"], default="A")
    ap.add_argument("--state", type=Path, help="phase B: the storage state e2e_ui_generate.py --state wrote")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    ui = f"{args.base}{args.ui_path}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            if args.phase == "B":
                if not args.state:
                    ap.error("--phase B needs --state")
                return phase_b(browser, ui, args.out, args.state)
            return phase_a(browser, args.base, ui, args.out, args.outputs)
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
