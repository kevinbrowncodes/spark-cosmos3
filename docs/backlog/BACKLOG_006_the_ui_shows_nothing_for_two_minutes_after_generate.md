# BACKLOG_006 — The UI shows nothing for two minutes after Generate

**Priority:** Medium — every single-clip generation, every user, every time
**Source:** STORY_025 E2E, 2026-09-07

## Summary

`POST /generate` upsamples the prompt with Gemma before returning a job id: 102-145 s
measured, up to five retries on a malformed reply. The Flow sidecar forwards that wait, and
the UI only creates a tile once the call returns. So pressing **Generate** produces no tile,
no spinner and no notice for around two minutes, on a box where a render then takes 45.

The agent path does not have this problem — it plans first, then submits with the script
already written, so its tiles appear immediately and the run's `step` explains itself.

## User impact

The UI looks broken or ignored the click; the natural response is to press Generate again,
which queues a second 45-minute render. It also fooled the E2E driver, whose 120 s tile wait
timed out while the job was in fact running (fixed by waiting 15 min, but that is a
workaround for the symptom).

## Rough scope

1. **Gateway returns first, upsamples after** — hand back a job id immediately in an
   `upsampling` state, do the Gemma call in the background, then submit to the engine. Job
   status grows one state; the sidecar and the UI already poll. Touches `gateway/server.py`,
   which EPIC_002 and EPIC_003 deliberately did not, so it needs its own story.
2. **Sidecar-side optimism** — the sidecar creates the tile at click time and reconciles when
   the gateway answers. Cheaper, no gateway change, but the tile has no job id for two
   minutes and a failed submit has to un-draw it.
3. **Just show the wait** — the UI already renders a `notice`; say "writing the prompt…".
   Smallest change, does not shorten anything, but stops the double-press.

## Dependencies

- Option 1 needs a story of its own (gateway change) and a look at how `progress` is derived
- Options 2 and 3 need an upstream flow change (BACKLOG_003's promotion path)

## Open questions

- Is the upsample worth 2 min on a single-clip generate at all, or should the UI offer to skip it (`upsample: false` already exists as a field)?
- If the gateway returns early, what should `GET /jobs/{id}` report while Gemma is still writing?
