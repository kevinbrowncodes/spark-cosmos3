# STORY_028 — The Flow UI gets a projects home page

**Epic:** EPIC_002 — A browser UI for generating and extending clips (follow-on)
**Depends on:** STORY_023–027; **flow `v0.2.0` released** (STORY-208 upstream)
**Blocked until:** `flow-ui-v0.2.0.tar.gz` exists on the flow repo's Releases page

As someone opening the Flow UI, I want to land on a page listing the projects
I have made — with a **New project** button — instead of being dropped straight
into a single editor, so that work on this box is organised rather than one
endless scroll.

This story is the **first exercise of the upgrade path** EPIC_002 promised:
bump the pin, rebuild, re-run conformance, *nothing else in this repo changes*.
If it needs more than that, the pinning design is wrong and this story should
say so.

## Acceptance Criteria

- [ ] `FLOW_VERSION` is `v0.2.0` in `.env.example` (and `.env` on the box)
- [ ] `docker compose build flow` pulls **both** the `flow-protocol` package and
      `flow-ui-v0.2.0.tar.gz` at that tag — one pin, two artefacts, still true
- [ ] `http://spark-1.local:8003/flow/` shows the **projects home**: a 3-column
      grid, a fixed **New project** button, hover rename and delete
- [ ] **New project** creates and opens a project; the card then appears on the home page
- [ ] A project that has rendered a clip shows that clip as its card thumbnail
      (served by `GET /flow/media/{id}?type=THUMBNAIL` — the sidecar's ffmpeg poster path)
- [ ] The ⋮ **About** panel reports: Flow UI `0.2.0`, Protocol `v1`, Gateway
      `same origin`, Model `Cosmos 3 Nano`
- [ ] Deleting a project removes it from the home page and **leaves the clips**
      in `~/Documents/flow-media/flow-outputs` and in the asset picker
- [ ] `flow-conformance http://localhost:8003` still passes 15/15
- [ ] `flow/tests/contract.sh` passes, extended to check `/flow/` serves the home
      page (it currently only asserts 200 + `text/html`)
- [ ] **`flow/gateway.py` and `flow/app.py` are unchanged** — proof the upgrade
      path holds. `git diff` on those two files across this story is empty
- [ ] The `crypto.randomUUID` shim in `flow/app.py` is **kept but verified redundant**:
      v0.2.0 fixes `uuid()` upstream, so the page must work with the shim removed
      too (checked once by hand, then the shim stays as belt-and-braces for the
      day someone pins an older `FLOW_VERSION`)
- [ ] README's Flow section mentions the home page; BUG_005 gains a note that
      the upstream fix shipped in v0.2.0
- [ ] `flow/` stays ≥ 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

**What upstream v0.2.0 contains** (`kevinbrowncodes/flow` STORY-208): the
projects home at `/`, adapter methods `listProjects` / `createProject` /
`renameProject` / `deleteProject`, `deleteProject` on the browser store, and a
guarded `uuid()`. Verified before release against this box's gateway from a
locally built `dist/` served on `:8005`; screenshots in
`docs/evidence/flow-home-page/`.

**Projects are still browser-side.** The home page lists the projects of the
browser looking at it — the Mac Studio and the Spark keep separate lists, and
clearing site data loses the grouping (never the clips). This is the moment
that becomes visible; **BACKLOG_004** holds the server-side option and the
`/flow/projects` route the protocol already anticipates. Do not treat a
"missing" project on another machine as a bug in this story.

**Nothing in the request contract moves.** No new gateway route, no protocol
change, no `server.py` edit. The only files this story may touch are
`.env.example`, `README.md`, `docs/bug/BUG_005…`, and `flow/tests/contract.sh`.

**If the build fails**, the likely causes in order: the tag does not exist yet;
the release workflow's version check rejected mismatched `package.json` /
`pyproject.toml`; or the tarball name changed. None of them are fixed by
editing this repo — fix the release upstream and rebuild.

## Testing Plan

- **Unit**: not applicable — no Python changes. `flow/tests/` runs unchanged
  and must stay green, which is itself the check that the pin bump did not
  alter our gateway code.
- **Integration**: the existing `flow/tests/test_flow_routes.py` suite runs
  against the rebuilt image's dependencies (the Docker `test` stage runs it at
  build time, so a `flow-protocol` v0.2.0 that broke `Cosmos3Gateway` would
  fail the build rather than ship).
- **Contract**: `flow/tests/contract.sh`, extended — `/flow/` must return the
  home page (assert it carries the projects grid markup, not just `text/html`).
  `flow-conformance http://localhost:8003` 15/15.
- **E2E**: drive the real UI headlessly at the LAN address
  (`flow/tests/e2e_ui_generate.py` covers the composer; add a home-page pass
  that creates a project, checks the card, and deletes it) plus a manual look
  on the Mac Studio. **No render** — the generation path does not change, so
  spending 44 GPU-minutes here proves nothing STORY_025 has not already proven.
- **Coverage**: `python3 -m pytest --cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Trivial if the design holds** — one environment variable, one rebuild. The
story exists to *prove* that, and to catch it in writing if it turns out false.
