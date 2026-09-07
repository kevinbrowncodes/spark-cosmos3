"""STORY_032 E2E: the Agent surface on the deployed sidecar, in headless Chromium at the LAN
address. Surface only — it starts no run and renders nothing, so it is safe to run any time
(~20 s). The run lifecycle itself is covered by `flow/tests/test_agent_runs_routes.py` and by
the browser drive recorded in `docs/evidence/story-032-agent-ui/`.

    python3 flow/tests/e2e_ui_agent.py --base http://192.168.1.33:8003
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://192.168.1.33:8003")
    ap.add_argument("--ui-path", default="/flow/")
    ap.add_argument("--out", type=Path, default=Path("docs/evidence/story-032-agent-ui"))
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    caps = json.load(urllib.request.urlopen(args.base + "/flow/capabilities"))
    agent = caps.get("agent")
    log("capabilities.agent:", agent)
    assert agent, "the sidecar does not declare the agent capability — is FLOW_VERSION new enough?"
    assert agent["confirm"] == "always", agent
    skills = json.load(urllib.request.urlopen(args.base + "/flow/agent/instructions"))
    log("skills via the protocol mirror:", len(skills), sorted(s["id"] for s in skills))
    assert skills, "no skills in PROMPTS_DIR"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{args.base}{args.ui_path}")
        page.get_by_role("button", name="New project").click()   # a fresh context has no grid yet
        page.wait_for_selector("[data-testid=composer]")

        pill = page.get_by_role("button", name="Agent", exact=True)
        off = pill.evaluate("b => getComputedStyle(b).backgroundColor")
        expect(pill).to_have_attribute("aria-pressed", "false")
        expect(page.get_by_role("button", name="Output settings")).to_have_count(1)
        pill.click()
        expect(pill).to_have_attribute("aria-pressed", "true")
        expect(page.get_by_role("button", name="Output settings")).to_have_count(0)   # model chip hides
        # the chip's background transitions over --dur-fast; poll it out (flow's own Part D does the same)
        deadline = time.monotonic() + 5
        on = off
        while on == off and time.monotonic() < deadline:
            on = pill.evaluate("b => getComputedStyle(b).backgroundColor")
            if on == off:
                page.wait_for_timeout(100)
        log("pill background off →", off, "| on →", on)
        assert on != off, "the pill did not change appearance"

        page.get_by_role("button", name="Agent instructions", exact=True).click()
        radios = page.get_by_test_id("instruction-picker").get_by_role("radio")
        expect(radios).to_have_count(len(skills), timeout=10_000)
        log("picker lists", radios.count(), "skills")
        page.screenshot(path=str(args.out / "16-deployed-8003-agent-picker.png"))
        page.keyboard.press("Escape")

        page.get_by_role("button", name="Agent settings", exact=True).click()
        settings = page.get_by_test_id("agent-settings")
        expect(settings.get_by_role("radio", name="Always", exact=True)).to_have_attribute("aria-checked", "true")
        clips = settings.get_by_role("spinbutton", name="Clips")
        log("confirm defaults to Always; clips input value:", clips.input_value())
        page.screenshot(path=str(args.out / "17-deployed-8003-agent-settings.png"))

        assert not errors, errors
        log("page errors:", errors, "— OK")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
