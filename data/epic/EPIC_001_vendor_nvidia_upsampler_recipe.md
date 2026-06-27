# EPIC 001 — Vendor NVIDIA's Official Upsampler Recipe into the Gateway

**Decision:** keep the hand-rolled gateway upsampler (do **not** add `cosmos-framework` as a
dependency on the ARM64 gateway container). Instead, *vendor* the two data files and *transcribe*
the small functions that the framework uses, so the gateway stays minimal while being byte-faithful
to NVIDIA's recipe. This removes the only real downside of hand-rolling: silent drift from the
official template + param-pinning.

**Scope:** the I2V path only (Cosmos3-Nano, dense `external_api` template, `claude-opus-4-8` as
upsampler — `UPSAMPLER_MODEL` env var remains the override point). Note: the paper validated
against an earlier Opus build; `claude-opus-4-8` is a deliberate upgrade. "Byte-faithful" refers
to the template + pinning logic, not the LLM's generated text.

**Replaces:** the existing `gateway/upsampler.py` is in production and working. Each story below
explicitly describes whether it replaces or extends the current module. No story removes the
existing fallback behaviour (no API key → prose; timeout/error → prose).

**Story numbering:** Stories 001–002 are already shipped. This epic runs STORY_003–STORY_008.

---

## Why

The gateway already owns the request contract (neg prompt, audio house style, Table 21 params,
field names). The one place it diverges from
`cosmos_framework.inference.prompt_upsampling` is **prompt assembly + param-pinning**. Rather than
import the package (which risks dragging heavy deps onto the aarch64 Spark container), copy the 2
data files + transcribe the 3–4 functions it depends on. They are tiny and stable.

---

## Source-of-truth file map

Upstream repo: **`github.com/nvidia/cosmos-framework`** (branch `main`).

| Item | Upstream path | Vendor into spark-cosmos3 as |
|---|---|---|
| Dense prompt template | `cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_prompt.txt` | `data/upsampler_template.txt` |
| JSON schema (fills `$json_template` slot) | `cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_json_schema.json` | `data/upsampler_schema.json` |
| `RESOLUTION_RATIO_DICT` (lines 59–88) | `cosmos_framework/inference/prompt_upsampling.py` | `data/resolution_ratio_dict.json` |
| `build_nl_description` + `build_t2v_prompt_text` (lines 121–193) | same | transcribe into `gateway/upsampler.py` |
| `SYSTEM_MESSAGE` + `build_i2v_messages` (lines 49–52, 254+) | same | transcribe intent into `gateway/upsampler.py` (see Story 6 note on API format) |
| `_apply_t2v_output_parameters` (lines 361–385) | same | transcribe into `gateway/upsampler.py` |
| Negative prompt (B.6) — **already done** | HF `nvidia/Cosmos3-Nano` → `assets/negative_prompt.json` | `data/neg.json` ✅ |

> **Template + schema travel together.** The `.txt` template has a `$json_template` placeholder
> that must be filled with the `.json` schema at assembly time. Vendor both or the prompt is
> incomplete.

---

## Story 3 — Vendor the template + schema files

Pull `t2v_i2v_video_prompt.txt` → `data/upsampler_template.txt` and
`t2v_i2v_video_json_schema.json` → `data/upsampler_schema.json`, verbatim.

**`string.Template` is safe here.** The schema is passed as a *value* to `.substitute()` and
substitution values are never re-scanned, so `$` characters inside the schema string cannot trigger
a `ValueError`. The template itself contains exactly the five known placeholders and nothing else
(verified against the upstream source). No brace-style fallback is needed.

**Regression guard:** after copying, grep the **template file** for `$` tokens and confirm only
the five known placeholders appear. Record this in `data/SOURCES.md`. If a future re-vendor adds a
new `$` token to the template, the grep will catch it before Story 5's code breaks at runtime.

**Acceptance**

- [ ] Both files copied byte-for-byte from upstream.
- [ ] `data/SOURCES.md` created (or updated) with: upstream raw URL, sha256, and date pulled for
      each file.
- [ ] `scripts/sync_config.sh` confirmed to include the new files in its sync set (they must reach
      the runtime location alongside `neg.json` and `audio.txt`).

---

## Story 4 — Vendor `RESOLUTION_RATIO_DICT`

Copy lines 59–88 of `prompt_upsampling.py` into `data/resolution_ratio_dict.json`.

```json
{
  "256": {"1,1":{"W":256,"H":256},"4,3":{"W":320,"H":256},"3,4":{"W":256,"H":320},"16,9":{"W":320,"H":192},"9,16":{"W":192,"H":320}},
  "480": {"1,1":{"W":640,"H":640},"4,3":{"W":736,"H":544},"3,4":{"W":544,"H":736},"16,9":{"W":832,"H":480},"9,16":{"W":480,"H":832}},
  "720": {"1,1":{"W":960,"H":960},"4,3":{"W":1104,"H":832},"3,4":{"W":832,"H":1104},"16,9":{"W":1280,"H":720},"9,16":{"W":720,"H":1280}},
  "768": {"1,1":{"W":1024,"H":1024},"4,3":{"W":1184,"H":880},"3,4":{"W":880,"H":1184},"16,9":{"W":1360,"H":768},"9,16":{"W":768,"H":1360}}
}
```

Verify against the local clone before committing.

**Acceptance**

- [ ] Dict values match the upstream clone exactly.
- [ ] The deployment's canonical size `720x1280` vertical maps correctly: tier `"720"`, aspect
      `"9,16"` → `{"W":720,"H":1280}`. ✓
- [ ] `data/SOURCES.md` updated with provenance for this file.

---

## Story 5 — Replicate the prompt-build (template fill) in the gateway

Transcribe `build_nl_description` + `build_t2v_prompt_text` (image_conditioned=True for I2V) into
`gateway/upsampler.py`, replacing the current hand-written prompt assembly. The existing fallback
paths (no API key, exception → prose) are preserved unchanged.

`build_upsampler_prompt` receives `resolution`, `aspect_ratio`, and `duration` as already-computed
strings — the shared `_parse_size` helper added in Story 7 is the single place that derives all
three from the client's raw `size`/`num_frames`/`fps`. Don't re-derive duration here.

```python
from string import Template
import json
from pathlib import Path

_DATA = Path(__file__).parent.parent / "data"
TEMPLATE = Template((_DATA / "upsampler_template.txt").read_text(encoding="utf-8").rstrip("\n"))
SCHEMA   = (_DATA / "upsampler_schema.json").read_text(encoding="utf-8").rstrip("\n")
RRD      = json.loads((_DATA / "resolution_ratio_dict.json").read_text(encoding="utf-8"))

I2V_INTRO = (
    "Given the attached starting frame image and the user's natural-language request below"
)
I2V_IMAGE_NOTE = (
    "\nIMPORTANT - IMAGE INPUT: The attached image is the first frame of the video. Use it as "
    "visual ground truth for subject appearance, setting, lighting, and colors. The natural-language "
    "request primarily describes temporal/action intent. Your JSON must be consistent with what is "
    "visible in the image.\n"
)

def build_nl_description(prompt, *, resolution, aspect_ratio, duration, fps):
    params = [
        f"resolution {resolution}", f"aspect_ratio {aspect_ratio}",
        f"duration {duration}", f"fps {fps}",
    ]
    return f"{prompt.strip()}\n\nOutput parameters: {', '.join(params)}."

def build_upsampler_prompt(prompt, *, resolution, aspect_ratio, duration, fps):
    nl = build_nl_description(
        prompt, resolution=resolution, aspect_ratio=aspect_ratio,
        duration=duration, fps=fps,
    )
    return TEMPLATE.substitute(
        intro=I2V_INTRO,
        image_note=I2V_IMAGE_NOTE,
        json_template=SCHEMA,
        nl_description=nl,
        resolution_ratio_dict=json.dumps(
            {r: {a: {"H": s["H"], "W": s["W"]} for a, s in ad.items()}
             for r, ad in RRD.items()},
            indent=2,
        ),
    )
```

Note: files are loaded at module import using `Path(__file__)` so the gateway process can be
started from any working directory.

**Acceptance**

- [ ] **Golden fixtures generated from the framework.** Before writing the pytest test, generate
      both fixture files directly from a local checkout of `cosmos-framework` by calling
      `build_t2v_prompt_text(..., image_conditioned=True)` with the same inputs. Commit the raw
      output (no editorial header, no whitespace reflow) as:
      - `gateway/tests/fixtures/upsampler_prompt_720_169.txt` (landscape, `16,9`, `"7s"`)
      - `gateway/tests/fixtures/upsampler_prompt_720_916.txt` (vertical, `9,16`, `"7s"`)
      These files are the authoritative baseline. Testing against a convenience copy (e.g.
      `cosmos-nano-built-upsampler-prompt.txt`) risks passing against a non-canonical baseline or
      failing on cosmetic differences in that file's header.
- [ ] **Golden test (landscape):** inputs `prompt="A car is driving fast. Rocks start falling from
      the mountains. The car makes a sudden stop."`, `resolution="720"`, `aspect_ratio="16,9"`,
      `duration="7s"`, `fps=24` → assembled text identical to
      `gateway/tests/fixtures/upsampler_prompt_720_169.txt`, byte-for-byte.
- [ ] **Golden test (vertical — our actual ship config):** `resolution="720"`, `aspect_ratio="9,16"`,
      `duration="7s"`, `fps=24` → assembled text identical to
      `gateway/tests/fixtures/upsampler_prompt_720_916.txt`, byte-for-byte.
- [ ] All existing `upsampler.py` unit tests (if any) still pass.

---

## Story 6 — Send the Anthropic chat with the official shape + sampling params

Replace the current `client.messages.create()` call in `gateway/upsampler.py` to match the
framework's `build_i2v_messages` intent: **image first, then text** in the user turn, using the
official sampling params.

**Anthropic SDK format (not OpenAI).** The NVIDIA framework targets OpenAI-compatible endpoints;
the gateway uses `AsyncAnthropic`. The translation:

```python
# system goes in the top-level `system=` parameter, NOT in messages[]
# image uses Anthropic's source block, NOT image_url

import base64

# Detect JPEG/PNG/WebP by magic bytes; don't trust file extension or upload Content-Type alone.
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8", "image/jpeg"),
    (b"\x89PNG", "image/png"),
    (b"RIFF", "image/webp"),   # WebP: RIFF????WEBP — prefix check is enough
]

def _detect_media_type(data: bytes) -> str:
    for magic, mime in _MAGIC:
        if data[:len(magic)] == magic:
            return mime
    return "image/jpeg"  # safe fallback; Anthropic will reject if truly wrong

def _image_block(image_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": _detect_media_type(image_bytes),
            "data": base64.standard_b64encode(image_bytes).decode("ascii"),
        },
    }

message = await client.with_options(timeout=120.0).messages.create(
    model=MODEL,
    system="You are a helpful assistant.",   # framework SYSTEM_MESSAGE verbatim
    messages=[
        {
            "role": "user",
            "content": [
                _image_block(seed_image_bytes),          # image first (framework order)
                {"type": "text", "text": build_upsampler_prompt(...)},
            ],
        }
    ],
    # Framework PromptUpsamplerConfig defaults. Setting temperature + top_p + top_k together
    # is intentional: it matches what NVIDIA validated. Anthropic recommends tuning only one,
    # but all three are accepted and the combination is harmless.
    temperature=0.7,
    top_p=0.8,
    top_k=20,
    max_tokens=8192,
)
```

**Parsing the response.** The template instructs the model to return only a JSON object wrapped in
a ` ```json ` fence. The gateway must extract and validate it before calling `_pin_output_params`:

```python
import json, re

def _extract_json(text: str) -> dict:
    """Strip the ```json fence and parse. Raises ValueError on any parse or type failure."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = match.group(1) if match else text.strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"expected dict, got {type(data).__name__}")
    return data
```

On failure, catch `ValueError`/`json.JSONDecodeError` and return `(None, "upsampler_error")` —
the same fallback path used for API errors. This is the seam between `messages.create()` returning
and `_pin_output_params` receiving its `data` argument.

Note: `max_tokens=8192` matches the framework default, but a rich scene caption can approach it.
If JSON-parse failures appear on complex prompts, bump it — Opus supports far more, and the
existing fallback handles the degraded path until you do.

**Acceptance**

- [ ] System text is exactly `"You are a helpful assistant."`.
- [ ] Image block appears before the text block in `content`.
- [ ] Sampling params match the framework defaults above (or any deliberate deviation is documented
      in a comment with the reason).
- [ ] `_extract_json` correctly strips the ` ```json ` fence and returns a `dict`.
- [ ] `_extract_json` raising → `(None, "upsampler_error")` (existing fallback path, not a new
      exception surface).
- [ ] Existing fallback behaviour unchanged: API key absent → `(None, "no_api_key")`; exception →
      `(None, "upsampler_error")`.

---

## Story 7 — Parse client size into upsampler inputs; pin output params before POSTing

**Gap from client contract to upsampler inputs.** The gateway receives `size` (e.g. `"720x1280"`),
`num_frames`, and `fps`. Stories 5 and 7 both need `resolution` (tier string `"720"`),
`aspect_ratio` (`"9,16"`), and `duration` (`"7s"`). A shared helper does the reverse-lookup once
and is the natural home for the 400-on-unsupported-size validation.

The schema's `duration` field is an enumerated set (`'2s'`–`'10s'`), which corresponds to a
maximum of 240 frames at 24 fps. The gateway contract accepts up to 300 frames, so `_parse_size`
must validate the derived duration label before returning it; otherwise `num_frames=300` at 24 fps
would produce `"12s"`, which is outside the schema enum and would cause vLLM-Omni to reject or
misinterpret the prompt.

```python
# Schema-allowed duration labels (from t2v_i2v_video_json_schema.json duration enum).
# At 24 fps this corresponds to a maximum of 240 frames (10 s × 24).
_ALLOWED_DURATIONS = frozenset(f"{s}s" for s in range(2, 11))  # '2s'..'10s'

def _parse_size(size: str, num_frames: int, fps: int) -> tuple[str, str, str]:
    """Reverse-lookup size string e.g. '720x1280' → (tier, aspect_ratio, duration_label).

    Returns ('720', '9,16', '7s') for size='720x1280', num_frames=189, fps=24.
    Raises ValueError (→ HTTP 400) if size is not in RESOLUTION_RATIO_DICT, or if the
    derived duration label falls outside the schema's allowed set.
    """
    try:
        w_str, h_str = size.split("x")
        w, h = int(w_str), int(h_str)
    except ValueError:
        raise ValueError(f"size must be WxH (e.g. '720x1280'), got: {size!r}")
    for tier, aspects in RRD.items():
        for aspect, dims in aspects.items():
            if dims["W"] == w and dims["H"] == h:
                duration = f"{int(num_frames / fps)}s"
                if duration not in _ALLOWED_DURATIONS:
                    _max_dur = max(_ALLOWED_DURATIONS, key=lambda s: int(s[:-1]))
                    raise ValueError(
                        f"num_frames={num_frames} at fps={fps} → duration '{duration}', "
                        f"which is outside the schema's allowed set ('2s'–{_max_dur!r}). "
                        f"Maximum is {_max_dur} "
                        f"({int(fps * int(_max_dur[:-1]))} frames at {fps} fps)."
                    )
                return tier, aspect, duration
    supported = ", ".join(
        f"{d['W']}x{d['H']}" for aspects in RRD.values() for d in aspects.values()
    )
    raise ValueError(f"size {size!r} not in RESOLUTION_RATIO_DICT. Supported: {supported}")
```

`_parse_size` is called once per request. Its three return values feed **both**
`build_upsampler_prompt` (Story 5) and `_pin_output_params` below — `duration` is never
re-derived, so the prompt's "Output parameters" line and the pinned JSON field are guaranteed
identical.

**After the model returns the structured JSON**, overwrite the four output fields so the caption
agrees with what you POST to vLLM-Omni (resolution/duration templates are disabled, so disagreement
causes inconsistency). Faithful to framework lines 361–385:

```python
def _pin_output_params(data: dict, *, resolution: str, aspect_ratio: str,
                       duration: str, fps: int) -> dict:
    pair = RRD[resolution][aspect_ratio]   # already validated by _parse_size
    data["resolution"]   = {"H": pair["H"], "W": pair["W"]}
    data["aspect_ratio"] = aspect_ratio
    data["duration"]     = duration        # from _parse_size — same value used in the prompt
    data["fps"]          = fps
    return data
```

Serialize the final caption with `ensure_ascii=True` (framework default `JSON_ENSURE_ASCII=1` —
matches how the model was trained):
```python
prompt_str = json.dumps(data, ensure_ascii=True)
```

**Acceptance**

- [ ] `_parse_size("720x1280", 189, 24)` → `("720", "9,16", "7s")`. Canonical vertical path.
- [ ] `_parse_size` with an unsupported size → `ValueError` → gateway returns HTTP 400 with a
      clear error message before any Opus API call.
- [ ] `_parse_size("720x1280", 300, 24)` → `ValueError` (derived `"12s"` is outside schema enum
      `'2s'`–`'10s'`) → HTTP 400. Max valid at 24 fps is 240 frames (`"10s"`).
- [ ] `resolution {H,W}` in the pinned JSON matches `RESOLUTION_RATIO_DICT[tier][aspect]` and the
      multipart `size` POSTed to vLLM-Omni.
- [ ] `duration` in the pinned JSON is identical to the `duration` string that appeared in the
      prompt's "Output parameters" line (both came from `_parse_size` — single source of truth).
- [ ] Caption serialized with `ensure_ascii=True`.

---

## Story 8 — Verification and drift guard

- [ ] **Golden prompt test** (Story 5 acceptance) is a `pytest` test in `gateway/tests/` that
      assembles the prompt and diffs byte-for-byte against
      `gateway/tests/fixtures/upsampler_prompt_720_169.txt` and
      `gateway/tests/fixtures/upsampler_prompt_720_916.txt` — both generated from the
      `cosmos-framework` clone, not from a convenience copy.
- [ ] **Checksum check script** (`scripts/check_upsampler_sources.sh`) re-fetches the two upstream
      raw files and compares sha256 against `data/SOURCES.md`; exits non-zero and prints a diff
      summary if upstream changed, so you decide whether to re-vendor.
- [ ] **End-to-end smoke**: one I2V job at `num_inference_steps=4` confirms the pinned JSON is
      accepted by vLLM-Omni and returns an MP4 at the requested size/frames.
- [ ] `docs/cosmos-framework.md` updated: change "unused here" note → "vendored: template, schema,
      resolution_ratio_dict, pinning logic (see `data/SOURCES.md`)".

---

## Done when

The gateway builds the upsampler prompt from the **vendored official template**, sends Opus the
correct Anthropic-SDK chat shape (image-first, official system message, framework sampling params),
**pins** the four output params against the canonical `resolution_ratio_dict`, serializes with
`ensure_ascii=True`, and a pytest golden test proves the assembled prompt matches NVIDIA's reference
byte-for-byte — with zero new runtime dependencies on the ARM64 gateway container and all existing
fallback paths intact.
