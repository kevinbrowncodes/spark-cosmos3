# STORY_027 — Open the Flow UI at `/flow/` from any machine on the LAN

**Epic:** EPIC_002 — A browser UI for generating and extending clips (follow-on)
**Depends on:** STORY_023
**Fixes:** BUG_005

As someone opening the editor from the Mac Studio, I want
`http://spark-1.local:8003/flow/` to load the Flow UI and work, so that the
address matches what the thing is called and the page doesn't crash outside
the Spark's own `localhost`.

## Acceptance Criteria

- [x] `GET /flow/` serves the UI; `GET /ui/` keeps working (upstream convention, `flow-conformance` docs); `GET /` redirects to `/flow/`
- [x] The API routes under `/flow/*` are unaffected: `/flow/capabilities`, `/flow/generate`, `/flow/jobs/{id}`, `/flow/media`, `/flow/uploads`, `/flow/media/{id}` still answer as before, and `flow-conformance` still passes
- [x] The served index page carries the `crypto.randomUUID` shim (BUG_005) on both paths; the bundle's own files (`/flow/assets/*`, `/ui/assets/*`) are served untouched from the pinned tarball
- [x] Headless Chromium against `http://192.168.1.33:8003/flow/` (insecure context) attaches a reference and types a prompt with zero page errors — the same dry-run that passes on `localhost`
- [x] README and `docs/api.md` name `/flow/` as the address; `contract.sh` checks `/flow/` → 200 html, `/ui/` → 200, `/` → 302, and the shim
- [x] `flow/` stays ≥ 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

- Starlette matches routes in registration order; the API router's paths are
  all deeper than `/flow/`, so an exact `GET /flow/` route plus a `StaticFiles`
  mount at `/flow` never shadow them. Register the index routes *before* the
  mounts so the shimmed page wins over the static `index.html`.
- The shim is injected server-side into the in-memory copy of `index.html`
  (`flow/app.py: inject_shim`) — nothing on disk is modified, so a
  `FLOW_VERSION` bump needs no change here and the shim is a no-op once the
  bundle guards the call itself.
- `crypto.getRandomValues` *is* available in insecure contexts; the shim builds
  a RFC 4122 v4 string from 16 random bytes. Verified in Node by the unit test.
- `create_app` from `flow_protocol.router` is replaced by explicit assembly in
  `build_app` (router → index routes → mounts); the router itself is untouched.

## Testing Plan

- **Unit**: `inject_shim` places the script right after `<head>` (or at the top when there is none) exactly once; the shim JS itself is executed in Node with `crypto.randomUUID` removed and must return RFC 4122 v4 strings (skipped if `node` is absent).
- **Integration**: `GET /flow/`, `GET /ui/` → 200 `text/html` containing the shim and the bundle `<script>`; `GET /flow/assets/<file>` → the raw file; `GET /` → 302 to `/flow/`; `GET /flow/capabilities` still the API; no UI dir → `/flow/` 404 and the API still up; in-process conformance green.
- **Contract**: `contract.sh` additions above.
- **E2E**: `flow/tests/e2e_ui_generate.py --base http://192.168.1.33:8003 --ui-path /flow/` dry-run with page-error capture; screenshot in `docs/evidence/STORY_027/`.
- **Coverage**: `--cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Small.** ~40 lines in `flow/app.py` and the tests.
