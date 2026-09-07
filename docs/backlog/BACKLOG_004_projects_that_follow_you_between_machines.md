# BACKLOG_004 — Projects that follow you between machines

**Status:** Open
**Priority:** Low until the Flow home page exists; **decide before it is built**, since the home page reads from whatever store wins
**Raised:** 2026-09-07, while planning the Flow projects home page (recon in progress upstream)
**Related:** BACKLOG_003 (library promotion), EPIC_002, flow `PROTOCOL.md` §"What the gateway does not do"

## Summary

Flow keeps **projects and batches in the browser**, in `localStorage` namespaced
per gateway origin (`flow:<gateway>:v1`, `src/adapter/store.js`). The gateway is
stateless apart from jobs and files. That is fine for the editor, but a
**projects home page makes the consequence visible**: the page lists the
projects of *the browser you are looking at*, not of the box.

## User impact

- Open `http://spark-1.local:8003/flow/` on the **Mac Studio** and on the
  **Spark** and you get two unrelated project lists — same renders underneath,
  different history.
- Safari vs Chrome on the same Mac: two lists.
- Clearing site data wipes the project list. **The media survives** (it is in
  `~/Documents/flow-media`), but the grouping, prompts and layout are gone.
- A second person on the LAN sees their own empty home page.

Nothing is lost that cannot be re-derived by hand from `/flow/media`, but the
home page will look broken to someone who expects it to be the box's history.

## Rough scope

The protocol already anticipates this — `PROTOCOL.md`: *"A `/flow/batches`
endpoint would be an additive v1.x change"*, and `store.js` is *"pluggable so a
gateway that grows a `/flow/batches` endpoint can replace it."*

1. **Upstream (flow):** additive `GET/PUT /flow/projects` + `/flow/batches`,
   an optional `capabilities.storage: "server"` flag, and a store implementation
   that uses them when the flag is present (localStorage otherwise, unchanged).
2. **Here:** implement those routes in the sidecar over a JSON file (or SQLite)
   under `FLOW_MEDIA_DIR` — the same directory that already holds the clips, so
   history and media are backed up together.

## Open questions

- Is browser-local actually fine? Kevin mostly drives one machine; the answer may
  legitimately be "leave it".
- If server-side: single shared history for everyone on the LAN, or per-browser
  identity? (No auth on this box, so shared is the honest default.)
- Does the home page need thumbnails the gateway can serve for a project whose
  media has been pruned, or is a dark card acceptable? (Google shows a dark card
  for an empty project.)

## Not blocking

The home page can ship browser-local first and gain a server store later —
`store.js` is designed for exactly that swap, and the home page code would not
change.
