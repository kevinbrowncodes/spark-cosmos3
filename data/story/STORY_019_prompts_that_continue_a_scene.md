# STORY_019 — Write prompts that continue a scene rather than describe a still

**Epic:** EPIC_001 — Continue an existing video clip
**Depends on:** STORY_017, STORY_018

As a pipeline operator, I want the prompt upsampler to understand that my source
clip is footage already in motion, so that the structured prompt describes what
happens **next** instead of describing the opening frame all over again.

## Acceptance Criteria

- [ ] `upsample=true` works on the V2V path — the `"v2v_not_supported"` fallback from STORY_017 is removed
- [ ] A V2V-specific upsampler template is vendored into `data/` alongside the existing I2V template
- [ ] The upsampler is given real motion context from the source clip, not a single frame
- [ ] `scene_imagination` summarises the source clip's subjects, motion history, and final visible configuration
- [ ] `temporal_caption` is the **future** timeline beginning where the source clip ends — it does not re-narrate the source
- [ ] `duration` in the emitted JSON is the **generated** length, not the total clip length
- [ ] `audio_description` covers the generated span only
- [ ] The V2V template is selectable with both reasoners (`opus`, `aeon`), matching STORY_015
- [ ] `upsampler_output` echoes the V2V structured prompt exactly, per the STORY_016 contract
- [ ] `./scripts/sync_config.sh --check` is clean after the new template lands in `data/`

## Technical Notes

**In pipeline terms**, the two inputs map cleanly onto the multi-clip workflow:
the conditioning video is the tail of the *previous* clip (what has already
happened) and the prose brief is the *next* script — `script2.txt` — describing
what should happen next. The upsampler's job is to fuse them into one JSON
prompt. It must not re-narrate the previous clip, or clip 2 spends its opening
seconds replaying clip 1's ending.

**The contract comes from the technical report**, line 2349 — NVIDIA's own V2V
upsampler user message. Its instruction block is the spec:

> *Prompt upsampler for a video-to-video continuation model. Treat the attached
> conditioning video as definitive visual and temporal ground truth for the
> observed prefix, and the text as future/action intent.*

And its task constraints, in order:

1. `scene_imagination` first — summarising the conditioning video's state,
   subjects, motion history, and **final visible configuration**
2. `temporal_caption` second — *"the future M:SS playback timeline **after** the
   conditioning video, preserving continuity with the observed prefix"*
3. `audio_description` third, aligned with visible future events
4. Copy the output parameters exactly
5. Preserve concrete facts from the conditioning video

This differs from our I2V template (`I2V_IMAGE_NOTE` in `gateway/upsampler.py`)
in kind, not degree. I2V says *"the attached image is the first frame, use it as
visual ground truth for appearance"* — a static description task. V2V says *the
video is ground truth for what has already happened, the text is intent for what
happens next* — a continuation task. Reusing the I2V template would produce a
careful description of frame 0 and throw away the motion history that is the
entire reason to use V2V.

**Duration semantics — this is the subtle one, and STORY_020 depends on it.**
In the report's V2V contract, `duration` describes the **continuation**, not the
whole clip. The Physics-IQ V2V protocol conditions on 3 s and predicts 5 s, and
the template instructs `Copy exactly: duration="0:05"` — the predicted 5 s, not
an 8 s total. So:

```
duration = (num_frames - condition_frames) / fps
```

Note the report's template uses `M:SS` (`"0:05"`) while our vendored schema
(`data/upsampler_schema.json`) uses `'5s'`. These are two different NVIDIA
artifacts — the report appendix versus the model-card upsampler template we
vendored in STORY_003. **Open question to resolve during implementation:** keep
our schema's `'Ns'` form for consistency with the I2V path, or follow the report's
`M:SS` on the V2V path. Prefer `'Ns'` unless the smoke output shows the model
mishandling it; consistency with the vendored schema is the safer default, and
`_ALLOWED_DURATIONS` already validates that form.

**Feeding motion to the reasoner.** Opus cannot consume video. Options, in
preference order:

1. **Extract N evenly-spaced frames** from the conditioning window and attach
   them as a multi-image message — cheap, no new services, and preserves the
   motion history that matters. Start with 4–5 frames across the 49-frame window.
2. Route V2V upsampling to **AEON** (STORY_015) if it accepts video directly.
   Confirm before assuming.

Whichever is chosen, the frames handed to the reasoner must come from the *same*
window the engine conditions on, or the prompt will describe motion the model
was never shown.

**Do not modify the I2V template.** Add a sibling. `upsampler.upsample()` gains a
`mode` parameter selecting between them.

## Testing Plan

**Unit** (required) — `gateway/tests/test_v2v_upsampler.py`:
- `mode="v2v"` selects the V2V template; `mode="i2v"` is byte-identical to today
- duration is computed from generated frames: 289 total − 49 conditioning at 24 fps → `'10s'`
- the frame-extraction helper returns N frames drawn from within the conditioning window
- a stubbed reasoner response validates against `data/upsampler_schema.json`
- the STORY_014 retry path and the STORY_016 `upsampler_output` echo both still hold on the V2V path

**Contract** (required) — curl with `upsample=true` and a video:
- response carries `prompt_source: "upsampled"` and a non-null `upsampler_output`
- the emitted JSON's `temporal_caption` starts at the continuation, not at 0:00
  of the source
- `reasoner=aeon` produces a valid structured prompt too

**Smoke** (required — the prompt reaching the engine changes) — 832×480,
`steps=35`, `frames=189`, `condition_seconds=2.0`, `upsample=true`. Compare
against the STORY_018 prose-path output from the same source clip and seed.
The upsampled continuation should follow the source's established motion rather
than restarting the action. ~26 min.

## Estimated Complexity

**High.** A new vendored template, a new reasoner input path (frame extraction),
duration semantics that STORY_020 builds on, and quality that can only be judged
by watching output.
