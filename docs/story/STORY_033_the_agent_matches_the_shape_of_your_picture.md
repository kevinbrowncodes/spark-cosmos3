# STORY_033 — The agent matches the shape of your picture

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Fixes:** BUG_012 (portrait seeds rendered into a landscape frame)

As someone starting an agent run from a photo on my phone, I want the clips to come out the
same shape as the photo, so that I get a usable video instead of a squashed one I have to
throw away after waiting 45 minutes for it.

## Acceptance Criteria

- [ ] **Shape comes from the seed, resolution comes from the request.** The agent keeps the
      pixel budget of whatever size was asked for and picks the offered size whose proportions
      match the seed: ask for `720x1280` with a landscape photo and you get `1280x720`, not a
      squashed portrait; ask for `832x480` with a portrait photo and you get `480x832`
- [ ] Where several offered sizes share the closest shape, the one nearest the **requested**
      size in pixel count wins, so a 480p request never silently becomes a 720p render
- [ ] This applies to every caller, including one that sends a size. A size arriving from the
      Flow UI is the UI echoing its own default, not a considered choice — treating it as
      binding is what put two landscape runs into a portrait frame on 2026-09-07 and is the
      reason this story exists. There is deliberately **no way to force a mismatched aspect**:
      the engine conditions on the seed as the first frame, so a mismatch is always a squash
- [ ] A **video** seed is measured the same way as an image seed (Extend runs keep the shape
      of the clip they continue)
- [ ] If the seed cannot be measured, the run falls back to the gateway's default size and
      says so in the run's record rather than failing
- [ ] `flow/runs.py` no longer contains a hardcoded `size`
- [ ] The chosen size appears in the run record and in `scripts/flow_agent.sh show`, so it is
      obvious before approving a plan what shape the clips will be

## Technical Notes

`Executor.create()` already has both halves of what this needs: the seed's path (from
`gateway.media_path`) and the gateway's capabilities (it calls `capabilities()` to normalise
the request). The missing pieces are a measurement and a choice.

- **Measure** with `ffprobe -show_entries stream=width,height`, which the sidecar already
  shells out to elsewhere (`has_audio` in `flow/gateway.py`) and which handles images and
  videos identically. The flow image ships ffmpeg.
- **Choose** by comparing aspect ratios in log space, so 9:16 and 16:9 sit the same distance
  from square and the comparison is symmetric. Rank the offered sizes by that distance, keep
  everything within a tolerance of the best (the ten sizes fall into five shapes, so this
  groups the two orientations of one shape), then break ties by absolute pixel-count
  difference from the **requested** size. That is what keeps the tier: `720x1280` and
  `1280x720` are the same 921,600 pixels, so a 720p request stays 720p.
- Sizes come from the video mode's `size` field options; there are ten today, five shapes in
  both orientations.
- Keep `DEFAULT_VALUES` for everything else (length, steps, sound, upsample, reasoner). Only
  the size becomes dynamic.

**Explicitly out of scope:** re-rendering anything already made, cropping or padding a seed
to fit a requested shape, and letting the UI offer a shape picker for agent runs. Also out of
scope: the same correction on the plain (non-agent) generate path — the UI's size control is
a deliberate choice there and the reference is not always a first frame, so that needs its own
story if it turns out to matter.

## Testing Plan

- **Unit** — required. The chooser: portrait, landscape and square seeds against the real
  option list; the tie-break holding the requested tier (a 720p request stays 720p, a 480p
  one stays 480p); an unmeasurable seed falling back to the requested size unchanged; a shape
  with no close match picking the nearest rather than failing. The measurement helper with
  ffprobe faked, plus one real-ffprobe test on a generated image (as `trim_prefix` already does).
- **Integration** — required. `POST /agent/runs` with a portrait seed records a portrait size
  and with a landscape seed a landscape one, including when the caller sends the opposite
  orientation at the same tier — the case the Flow UI hits.
- **Contract** — required. `flow/tests/contract.sh` gains a check that a run created from the
  bundled portrait fixture reports a portrait size.
- **E2E** — required, but **without a new render**: create a run from the real portrait seed
  on the box and assert the recorded size is portrait, then abandon it before approval.
  Proving the pixels are right needs a 45-minute render and BUG_012 already carries the
  measurement showing why they were wrong; a fresh render would only confirm arithmetic.
- **Coverage** — `pytest --cov=flow --cov-fail-under=95` stays green.

## Estimated Complexity

Small. One helper, one measurement, one call site; the tests are the bulk of it.
