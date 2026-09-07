# Agent prompt library

Each `*.md` here is one **skill** the agent can run (EPIC_003). Drop Kevin's
skill files in as-is — the frontmatter they already carry is the contract.

Installed 2026-09-07 (verbatim, named after their frontmatter `name`):
`cosmos-3-i2v-scene`, `cosmos-3-i2v-amg-scene`, `cosmos-3-i2v-helios-scene`,
`cosmos-3-i2v-time-forecast-scene`, `cosmos-3-i2v-time-thirst-scene`,
`cosmos-3-i2v-weber-scene`, `cosmos-3-i2v-time-youtube-formula-scene`, plus the
neutral `example-forecast-scene` used by the docs and the smoke tests. All eight
carry `{{COUNT}}`, so any of them can write 1-12 clips. `./data` is mounted
read-only into the flow container and read per request — adding a file here
shows up in the picker without a restart.


```yaml
---
name: cosmos-3-i2v-time-thirst-scene      # picker id; stable, kebab-case
description: >-                           # picker subtitle (first sentence is shown)
  Writes MOTION INTENT scripts for …
---
```

Rules the agent applies:

- A skill containing `{{COUNT}}` accepts `count` ≥ 1 and must emit exactly that
  many `<<<SCRIPT n>>> … <<<END SCRIPT>>>` blocks (plus optional `<<<TITLES>>>`
  and `<<<SUMMARY>>>`). A wrong count is a failed plan, retried up to 5 times.
- A skill **without** `{{COUNT}}` is count-locked to 1; a marker-less reply is
  accepted as the single script.
- Files are read from `/data/prompts` inside the `flow` container (this
  directory, mounted read-only). Edits take effect on the next plan — no
  restart, no rebuild.
- Keep them UTF-8. Em-dashes and emoji in the titles block are fine; the
  parser only cares about the `<<<…>>>` markers.

Nothing here is sent anywhere but the local Ollama on this box.
