# Agent prompt library

Each `*.md` here is one **skill** the agent can run (EPIC_003). Drop Kevin's
skill files in as-is — the frontmatter they already carry is the contract:

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
