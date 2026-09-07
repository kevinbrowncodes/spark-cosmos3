#!/usr/bin/env python3
"""Drive the real Flow UI in headless Chromium: attach a still, type a prompt,
press Generate, and screenshot the tile as it runs and when it finishes
(STORY_025 E2E). Without --submit it stops just before Generate — a free
selector check.

  .venv/bin/python flow/tests/e2e_ui_generate.py --still ~/Documents/cosmos-media/input_cap_guy.jpg \
      --prompt "…" --out docs/evidence/STORY_025 --submit --timeout 3600
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8003")
    ap.add_argument("--ui-path", default="/flow/", help="where the UI is served (/flow/ or /ui/)")
    ap.add_argument("--still", type=Path, required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", type=Path, default=Path("evidence"))
    ap.add_argument("--submit", action="store_true", help="actually press Generate and wait for the tile")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--shot-every", type=float, default=300.0)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    jobs: list[dict] = []
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("response", lambda r: r.url.endswith("/flow/generate") and r.status == 202 and jobs.append(r.json()))
        page.on("pageerror", lambda e: errors.append(str(e)))      # BUG_005 regression guard
        page.goto(f"{args.base}{args.ui_path}", wait_until="networkidle", timeout=60_000)
        print("secure context:", page.evaluate("window.isSecureContext"))

        page.locator('[aria-label="Add assets"], [title="Add assets"]').first.click()
        dialog = page.locator('[role="dialog"][aria-label="Add to Prompt"]')
        dialog.wait_for(timeout=10_000)
        dialog.locator('input[type="file"]').set_input_files(str(args.still))
        add = dialog.get_by_role("button", name="Add to Prompt")
        page.wait_for_function("b => !b.disabled", arg=add.element_handle(), timeout=30_000)
        add.click()
        dialog.wait_for(state="hidden", timeout=10_000)

        prompt = page.locator('[aria-label="Prompt"]')
        prompt.click()
        page.keyboard.type(args.prompt)
        page.wait_for_timeout(500)
        page.screenshot(path=str(args.out / "01-composed.png"))
        print("composed: reference attached, prompt typed")
        if errors:
            print("PAGE ERRORS:", errors)
            browser.close()
            return 1
        if not args.submit:
            browser.close()
            return 0

        page.locator('[aria-label="Generate"]').click()
        tile = page.locator('[data-testid="tile"]').first
        tile.wait_for(timeout=120_000)
        page.wait_for_timeout(3_000)
        page.screenshot(path=str(args.out / "02-submitted.png"))
        print("submitted:", json.dumps(jobs[-1]) if jobs else "(no /flow/generate response captured)")

        started = time.monotonic()
        last_shot = started
        last_pct = None
        while time.monotonic() - started < args.timeout:
            page.wait_for_timeout(15_000)
            if tile.locator("img").count() and "poster" in (tile.locator("img").first.get_attribute("class") or ""):
                page.screenshot(path=str(args.out / "04-done.png"))
                print(f"done after {int(time.monotonic() - started)} s")
                browser.close()
                return 0
            pct = tile.inner_text().strip().replace("\n", " ")
            if "Failed" in pct:
                page.screenshot(path=str(args.out / "04-failed.png"))
                print("FAILED:", tile.get_attribute("title") or pct)
                browser.close()
                return 1
            if pct != last_pct or time.monotonic() - last_shot >= args.shot_every:
                page.screenshot(path=str(args.out / "03-running.png"))
                print(f"{int(time.monotonic() - started):5d} s  tile: {pct}")
                last_pct, last_shot = pct, time.monotonic()
        print("timed out")
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
