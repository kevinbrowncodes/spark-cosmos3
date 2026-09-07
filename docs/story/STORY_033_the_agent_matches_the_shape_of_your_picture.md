# STORY_033 — The agent matches the shape of your picture

**Epic:** EPIC_003 — The agent plans a scene, then renders it
**Fixes:** BUG_012 (portrait seeds rendered into a landscape frame)

As someone starting an agent run from a photo on my phone, I want the clips to come out the
same shape as the photo, so that I get a usable video instead of a squashed one I have to
throw away after waiting 45 minutes for it.

## Acceptance Criteria

- [ ] The agent picks the render size from the **seed's own proportions**, choosing among the
      sizes the gateway offers rather than a constant: a portrait photo gives a portrait
      clip, a landscape photo a landscape one, a square photo a square one
- [ ] Where several offered sizes share the closest shape, the one nearest the gateway's own
      default in pixel count wins, so the agent does not silently jump from 480p to 720p
- [ ] An explicit size — `scripts/flow_agent.sh run … --size 480x832`, or `values.size` from
      the UI — always wins over the automatic choice
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
  from square and the comparison is symmetric. Rank the offered sizes by that distance, then
  break ties by absolute pixel-count difference from the capability default.
- Sizes come from the video mode's `size` field options; there are ten today, five shapes in
  both orientations.
- Keep `DEFAULT_VALUES` for everything else (length, steps, sound, upsample, reasoner). Only
  the size becomes dynamic.

**Explicitly out of scope:** re-rendering anything already made, cropping or padding a seed
to fit a requested shape, and letting the UI offer a shape picker for agent runs. If the seed
and an explicit size disagree, the explicit size wins and the engine squashes as it does
today — that is the caller's stated intent.

## Testing Plan

- **Unit** — required. The chooser: portrait, landscape and square seeds against the real
  option list; the tie-break preferring the default's pixel count; an unmeasurable seed
  falling back; an explicit size overriding. The measurement helper with ffprobe faked, plus
  one real-ffprobe test on a generated image (the suite already does this for `trim_prefix`).
- **Integration** — required. `POST /agent/runs` with a portrait seed records a portrait
  size; with an explicit `values.size` records that size unchanged; both through the
  `TestClient` with the gateway faked.
- **Contract** — required. `flow/tests/contract.sh` gains a check that a run created from the
  bundled portrait fixture reports a portrait size.
- **E2E** — required, but **without a new render**: create a run from the real portrait seed
  on the box and assert the recorded size is portrait, then abandon it before approval.
  Proving the pixels are right needs a 45-minute render and BUG_012 already carries the
  measurement showing why they were wrong; a fresh render would only confirm arithmetic.
- **Coverage** — `pytest --cov=flow --cov-fail-under=95` stays green.

## Estimated Complexity

Small. One helper, one measurement, one call site; the tests are the bulk of it.
