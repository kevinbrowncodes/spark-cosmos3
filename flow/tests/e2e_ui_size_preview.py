"""STORY_034 E2E: on the box, the composer shows the corrected size BEFORE Generate is pressed.

Drives the deployed sidecar at the LAN address in headless Chromium. Attaches references of
known shape and reads the composer's size chip; for the photo it also creates a run (which is
abandoned before it plans anything expensive… it will plan, so the run is deleted straight
after) and checks the recorded size equals what the chip showed. No render.

    python3 flow/tests/e2e_ui_size_preview.py --base http://192.168.1.33:8003 \\
        --photo in:8e8ca68e-01.jpeg --portrait-video out:video_gen_95480fff67924d2294e5854a6f0cd290.mp4 \\
        --landscape-video out:run_9b56240457f8_full.mp4
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


def attach(page, name_fragment: str) -> None:
    page.get_by_role("button", name="Add assets").click()
    dialog = page.get_by_role("dialog", name="Add to Prompt")
    dialog.locator("button").filter(has_text=re.compile(re.escape(name_fragment))).first.click()
    dialog.get_by_role("button", name="Add to Prompt").click()
    expect(dialog).to_have_count(0)


def chip_size(page, timeout_ms: int = 15_000) -> str:
    chip = page.get_by_test_id("agent-size")
    expect(chip).to_be_visible(timeout=timeout_ms)
    return re.search(r"\d+x\d+", chip.inner_text()).group(0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://192.168.1.33:8003")
    ap.add_argument("--photo", required=True, help="media id of a landscape photo already uploaded")
    ap.add_argument("--portrait-video", required=True, help="media id of a 720x1280 clip")
    ap.add_argument("--landscape-video", required=True, help="media id of an 832x480 or 1280x720 clip")
    ap.add_argument("--out", type=Path, default=Path("docs/evidence/story-034-size-preview"))
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    runs_dir = Path.home() / "Documents/flow-media/flow-runs"

    caps = json.load(urllib.request.urlopen(args.base + "/flow/capabilities"))
    log("agent.shape_from_seed:", caps["agent"].get("shape_from_seed"))
    assert caps["agent"].get("shape_from_seed") is True, "the deployed sidecar must declare shape_from_seed"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{args.base}/flow/")
        page.get_by_role("button", name="New project").click()
        page.wait_for_selector("[data-testid=composer]")
        page.get_by_role("button", name="Agent", exact=True).click()
        page.get_by_role("button", name="Agent instructions", exact=True).click()
        page.get_by_test_id("instruction-picker").get_by_role("radio").first.click()
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("agent-size")).to_have_count(0)          # nothing attached → nothing claimed

        # 1. a landscape photo against the UI's portrait default
        attach(page, args.photo.split(":", 1)[1])            # the picker lists full file names
        shown = chip_size(page)
        log("photo attached → chip shows", shown)
        assert shown == "1280x720", shown
        page.screenshot(path=str(args.out / "01-photo-chip-1280x720.png"))
        page.get_by_role("button", name="Generate", exact=True).click()
        expect(page.get_by_test_id("run-step")).to_be_visible()
        runs = json.load(urllib.request.urlopen(args.base + "/flow/agent/runs"))
        run = max(runs, key=lambda r: r["created_at"])
        log("run", run["id"], "recorded", run["values"]["size"])
        assert run["values"]["size"] == shown, (run["values"]["size"], shown)
        page.screenshot(path=str(args.out / "02-run-recorded-same-size.png"))
        (runs_dir / f"{run['id']}.json").unlink(missing_ok=True)             # abandon it — no render
        page.get_by_role("button", name="Close").click()

        # 2. a portrait clip picked for an Extend
        page.get_by_role("button", name="Agent", exact=True).click() if page.get_by_role("button", name="Agent", exact=True).get_attribute("aria-pressed") != "true" else None
        attach(page, args.portrait_video.split(":", 1)[1])
        shown = chip_size(page)
        log("portrait clip attached → chip shows", shown)
        assert shown == "720x1280", shown
        page.screenshot(path=str(args.out / "03-portrait-clip-chip-720x1280.png"))
        page.get_by_role("button", name="Remove reference").click()
        expect(page.get_by_test_id("agent-size")).to_have_count(0)          # reverts when removed

        # 3. a landscape clip picked for an Extend
        attach(page, args.landscape_video.split(":", 1)[1])
        shown = chip_size(page)
        log("landscape clip attached → chip shows", shown)
        assert shown == "1280x720", shown
        page.screenshot(path=str(args.out / "04-landscape-clip-chip-1280x720.png"))

        assert not errors, errors
        log("page errors:", errors, "— OK")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
