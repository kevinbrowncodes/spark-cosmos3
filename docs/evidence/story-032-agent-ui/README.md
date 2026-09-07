# STORY_032 evidence — the Agent pill in the Flow UI

Captured 2026-09-07, headless Chromium at the LAN address (plain http).
01–15 were driven against a host-run sidecar serving the unreleased v0.2.0 bundle,
because the deployed image still pinned v0.1.0 at the time; 16–18 and
`verify-deployed.txt` are the deployed `v0.2.0` image (`cosmos3-flow`).

| File | What it shows |
|---|---|
| `01-settings-real-backend.png` | agent settings reading the gateway's real sizes |
| `02-instruction-picker-real-skill.png` | the picker listing a real `data/prompts` skill |
| `02b-instruction-picker-all-eight-skills.png` | all eight skills after Kevin's seven were installed |
| `03-settings-count-1-confirm-always.png` | confirm defaults to Always; count set to 1 |
| `04-seed-attached-send-enabled.png` | agent mode requires a seed; Generate enables once attached |
| `05-run-created-planning-1-tile.png` | the run appears as a batch of `count` tiles while planning |
| `06-review-one-script.png` | the review view with the script, titles and arc |
| `07-cli-run-appears-as-second-batch.png` | a run created by `scripts/flow_agent.sh` showing up in the same project |
| `08-script-edited-persisted.png` | an edit on blur, persisted to the backend |
| `09-script-rewritten.png` | Rewrite changing only that script |
| `10-approved.png` / `11-rendering.png` | Approve → Queued → Rendering with live percentage |
| `11b-expand-reopens-panel-after-bug-001.png` | the Expand icon reopening the panel (flow BUG-001) |
| `12-done-tile-poster.png` / `13-run-history-done.png` / `14-done-tile-open.png` | the finished clip as a tile, in run history, and opened |
| `15-home-project-card.png` | the project card on the home page |
| `16-deployed-8003-agent-picker.png` / `17-deployed-8003-agent-settings.png` | the same surface on the deployed v0.2.0 image |
| `18-failed-run-reason-and-resume.png` | a failed run showing its reason and offering Resume |
| `verify-deployed.txt` | `flow/tests/e2e_ui_agent.py` output against `:8003` |
