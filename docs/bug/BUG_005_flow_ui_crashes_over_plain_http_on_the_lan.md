# BUG_005 — The Flow UI crashes with `crypto.randomUUID is not a function` when opened over plain http on the LAN

**Status:** Resolved (shimmed in the sidecar — STORY_027; upstream fallback still to be filed)
**Found:** 2026-09-07, first open from the Mac Studio at `http://192.168.1.33:8003/ui/`
**Affects:** every browser on the LAN; not `localhost` on the Spark itself

## Summary

Flow v0.1.0 calls `globalThis.crypto.randomUUID()` unguarded
(`src/adapter/contract.js:266`, `export const uuid = () => globalThis.crypto.randomUUID()`).
Browsers expose `crypto.randomUUID` **only in secure contexts** — `https://`
or `http://localhost`. Over `http://192.168.1.33:8003` (and `http://spark-1.local:8003`)
it is `undefined`, so the first batch/project id throws and the editor shows
`globalThis.crypto.randomUUID is not a function`.

## Steps to reproduce

1. From any other machine: open `http://192.168.1.33:8003/ui/`
2. Type a prompt, attach a reference, press Generate (or just load the page, depending on the browser)
3. Error banner as above; nothing is submitted

`http://localhost:8003/ui/` on the Spark works — `localhost` is a secure context,
which is why the STORY_023 headless check passed.

## Expected vs actual

- **Expected:** the UI works wherever the gateway is reachable; this is a single-user LAN box with no TLS.
- **Actual:** unusable from every machine except the Spark itself.

## Root cause

Upstream: `crypto.randomUUID` is secure-context-only; `crypto.getRandomValues`
is not, and is enough to build a v4 UUID. The proper fix belongs in the flow
repo (`contract.js`): fall back to `getRandomValues` when `randomUUID` is absent.

## Acceptance criteria

- [x] The served index page (`/flow/`, `/ui/`) carries a tiny shim that defines `crypto.randomUUID` from `getRandomValues` when it is missing — applied by the sidecar at serve time, so it survives `FLOW_VERSION` bumps and disappears with no code change once upstream ships the fallback
- [x] Headless Chromium against the **LAN address** (an insecure context) composes and attaches a reference with zero page errors
- [x] `contract.sh` asserts the shim is present in the served page
- [x] Upstream issue/patch noted here once filed in `kevinbrowncodes/flow` — shipped in `v0.2.0`: `uuid()` in `src/adapter/contract.js` falls back to `getRandomValues`, confirmed in the published bundle and by driving the page with `crypto.randomUUID` absent

## Resolution

2026-09-07, STORY_027: `flow/app.py` injects a `crypto.randomUUID` polyfill
(built on `getRandomValues`) into the in-memory copy of `index.html` served at
`/flow/` and `/ui/`; the pinned bundle on disk is untouched and the shim is a
no-op once the bundle guards the call itself. Verified with headless Chromium
against `http://192.168.1.33:8003/flow/` (`isSecureContext: false`): zero
page errors, reference attached, prompt typed — evidence in
`docs/evidence/STORY_027/` (before/after). The upstream fix — a
`getRandomValues` fallback in `src/adapter/contract.js` — is still to be filed
in `kevinbrowncodes/flow`; when it ships, nothing here needs to change.

**Update 2026-09-07 (STORY_028):** the upstream fix shipped in flow `v0.2.0` — `uuid()` in
`src/adapter/contract.js` falls back to `getRandomValues` when `crypto.randomUUID` is absent.
The sidecar's shim stays as belt-and-braces for anyone pinning an older `FLOW_VERSION`; it
was verified redundant by driving the v0.2.0 bundle over plain http with the shim stripped
(evidence in `docs/evidence/story-028-home-page/`).
