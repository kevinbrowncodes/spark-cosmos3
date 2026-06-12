# Prompting Cosmos 3

How the model wants to be prompted, from the technical report (Appendix A
schema, Appendix B.1 upsampler template, §6.3.2) — and how that maps to our
pipeline. Full verbatim text: docs/cosmos-3-technical-report.md.

## The core fact

Cosmos 3 was trained on **structured JSON captions**, not free prose. Prompts
that match that distribution generate better. NVIDIA's reference stack never
sends raw user text to the generator — a *prompt upsampler* (Claude Opus 4.6
or the Cosmos 3 Reasoner) first expands the request into the structured
schema. Our pipeline currently sends dense prose; it works, but the structured
format is the documented quality lever.

## Image/static schema (Appendix A.2, p. 80)

Top-level fields the captioner used in training:

| Field | Contents |
|---|---|
| `subjects[]` | per-subject identity, appearance, spatial placement, pose, clothing, expression; demographics/facial attributes when visible |
| `subject_details` | open-ended attributes that don't fit one subject slot |
| `background_setting` | global scene context and environment |
| `lighting` | illumination, directionality, shadows, effects |
| `aesthetics` | composition, palette, mood, visual patterns |
| `cinematography` | framing, camera angle, depth of field, focus, lens |
| `style_medium` / `artistic_style` | medium and rendering style |
| `context` | high-level narrative/situational context |
| `text_and_signage_elements[]` | visible text and its placement |
| `comprehensive_t2i_caption` | natural-language summary of the structured fields |
| `resolution` / `aspect_ratio` | size metadata |

Note this is the same field family as our negative prompt (`data/neg.json`)
— the negative prompt is a *negative instance* of this schema. That symmetry
is why it works.

## Video additions (Appendix A.3, p. 83)

| Field | Contents |
|---|---|
| `actions[]` | key visual actions in chronological order |
| `segments` | distinct temporal segments (shot/scene/meaningful change) |
| `transitions` | notable transitions between segments |
| `temporal_caption` | dense description of all temporal changes |
| `audio_description` | speech, music, SFX, ambient audio |
| `duration` / `fps` / `resolution` / `aspect_ratio` | media metadata |

Plus per-subject temporal fields: `action`, `state_changes`, `camera_motion`.

## The upsampler recipe (Appendix B.1, pp. 84–86; §6.3.2 p. 74)

The official template instructs the upsampler LLM to write, **in order**:

1. `scene_imagination` — scene layout and world state first;
2. `temporal_caption` — a timestamped `M:SS` playback timeline of events;
3. `audio_description` — aligned with the visual beats;
4. exact media controls copied through (`duration`, `fps`, `aspect_ratio`).

That ordering (space → time → sound → controls) is itself the prompting
guidance: describe the world, then its evolution, then what it sounds like.

## What this means for our pipeline

- **Today (prose prompts):** our prompts already do well when they follow the
  same shape — establish subjects/setting/lighting/camera first, then narrate
  the motion beat-by-beat in chronological order, then (since we generate
  sound) describe the audio. Avoid prompt text about resolution or duration —
  those are request fields, and our client disables the resolution/duration
  prompt templates (`use_resolution_template/use_duration_template: false`).
- **Upsampling is implemented in the gateway** (`gateway/upsampler.py`):
  `/generate` expands the prose brief into the Appendix B.1 structured JSON
  via the Anthropic API (Claude, the same vendor NVIDIA used), grounded on
  the seed image, with the audio house style folded into the
  `audio_description` constraint. Requires `ANTHROPIC_API_KEY` in `.env`;
  without it (or on any failure) the gateway falls back to the prose path.
  Opt out per request with `upsample=false`; check `prompt_source` in the
  job response to see which path ran.
- **Negative prompt:** keep `data/neg.json` as-is (benchmark-tuned, Appendix
  B.6). Don't extend it with ad-hoc terms; quality issues are better attacked
  from the positive prompt's structure.
