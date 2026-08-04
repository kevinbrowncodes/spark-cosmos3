"""Prompt upsampler — NVIDIA's documented pre-generation step.

Cosmos 3 was trained on structured JSON captions; NVIDIA's production stack
converts user prompts into that format with an LLM upsampler before
generation (technical report §6.3.2; template: Appendix B.1, I2V variant).
This module implements that step with the **local Gemma model over Ollama**
by default, grounding on the conditioning media per the official template.
Opus remains selectable via `reasoner="opus"` for when an API key is present.

Gemma is the default because it is the only reasoner that works unattended on
this box (STORY_022): Opus needs credit, and AEON was removed after being
unreachable throughout. Defaulting to a reasoner that cannot answer is how every
`upsample=true` request silently degraded to prose.

Failure of any kind returns None and the gateway falls back to the prose prompt
path — upsampling can never block a render.
"""

import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path
from string import Template

import anthropic
import httpx
from anthropic import AsyncAnthropic

# ---------------------------------------------------------------------------
# Official NVIDIA template-based prompt assembly (Story 5)
# Transcribed from cosmos_framework.inference.prompt_upsampling lines 121–193.
# Called by upsample() once _parse_size is wired in Story 7.
# ---------------------------------------------------------------------------

_DATA = Path(__file__).parent.parent / "data"
TEMPLATE = Template((_DATA / "upsampler_template.txt").read_text(encoding="utf-8").rstrip("\n"))
SCHEMA = (_DATA / "upsampler_schema.json").read_text(encoding="utf-8").rstrip("\n")
RRD = json.loads((_DATA / "resolution_ratio_dict.json").read_text(encoding="utf-8"))

I2V_INTRO = (
    "Given the attached starting frame image and the user's natural-language request below"
)
I2V_IMAGE_NOTE = (
    "\nIMPORTANT - IMAGE INPUT: The attached image is the first frame of the video. "
    "Use it as visual ground truth for subject appearance, setting, lighting, and colors. "
    "The natural-language request primarily describes temporal/action intent. "
    "Your JSON must be consistent with what is visible in the image.\n"
)


# V2V variant (STORY_019). Transcribed from the technical report's own V2V
# upsampler user message (docs/cosmos-3-technical-report.md line 2349) — the
# ordering of scene_imagination -> temporal_caption -> audio_description and the
# "conditioning video is ground truth for the prefix, text is future intent"
# framing are NVIDIA's, not ours. Kept as constants rather than a data/ file
# because data/ holds files pulled verbatim from cosmos-framework (see
# data/SOURCES.md, "Do not hand-edit"); there is no upstream V2V template to
# vendor, and the shared base template is already vendored.
V2V_INTRO = (
    "Given the attached frames, sampled in order from a conditioning video that "
    "immediately precedes the video to be produced, and the user's "
    "natural-language request below"
)
V2V_VIDEO_NOTE = (
    "\nIMPORTANT - CONDITIONING VIDEO INPUT: The attached frames are consecutive "
    "samples from the END of a conditioning video. Treat them as definitive "
    "visual and temporal ground truth for what has ALREADY happened. The "
    "natural-language request describes future/action intent — what happens NEXT.\n"
    "The video you are describing STARTS where the final attached frame ends. "
    "It is a continuation, not a retelling.\n"
    "1. Ground subjects, background_setting, lighting and context in the "
    "conditioning frames: their state at the final frame, and the direction and "
    "speed of any motion already underway.\n"
    "2. Write temporal_caption as the future playback timeline that FOLLOWS the "
    "conditioning video, preserving continuity with the observed motion. Do NOT "
    "re-narrate the attached frames — the first moment you describe is the "
    "moment after the last attached frame.\n"
    "3. Write audio_description aligned with visible future events.\n"
    "4. Preserve concrete facts from the conditioning frames: subject "
    "appearance, setting, lighting, colours, and motion already in progress.\n"
    "5. Use ONLY the keys in the output template. Do not add keys — in "
    "particular there is no scene_imagination field in this schema.\n"
)


def build_nl_description(
    prompt: str,
    *,
    resolution: str,
    aspect_ratio: str,
    duration: str,
    fps: int,
) -> str:
    params = [
        f"resolution {resolution}",
        f"aspect_ratio {aspect_ratio}",
        f"duration {duration}",
        f"fps {fps}",
    ]
    return f"{prompt.strip()}\n\nOutput parameters: {', '.join(params)}."


def build_upsampler_prompt(
    prompt: str,
    *,
    resolution: str,
    aspect_ratio: str,
    duration: str,
    fps: int,
    mode: str = "i2v",
) -> str:
    """Assemble the NVIDIA upsampler prompt from the vendored template.

    `mode` swaps the two template slots the base file exposes: I2V describes a
    starting frame, V2V describes a continuation of motion already underway.
    """
    nl = build_nl_description(
        prompt, resolution=resolution, aspect_ratio=aspect_ratio,
        duration=duration, fps=fps,
    )
    rrd_text = json.dumps(
        {r: {a: {"H": s["H"], "W": s["W"]} for a, s in ad.items()} for r, ad in RRD.items()},
        indent=2,
    )
    return TEMPLATE.substitute(
        intro=V2V_INTRO if mode == "v2v" else I2V_INTRO,
        image_note=V2V_VIDEO_NOTE if mode == "v2v" else I2V_IMAGE_NOTE,
        json_template=SCHEMA,
        nl_description=nl,
        resolution_ratio_dict=rrd_text,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = os.environ.get("UPSAMPLER_MODEL", "claude-opus-4-8")

# Default reasoner. Local, free, no key. Reachable from the container via
# host.docker.internal (see docker-compose.yml extra_hosts).
GEMMA_URL = os.environ.get("GEMMA_URL", "http://host.docker.internal:11434")
GEMMA_MODEL = os.environ.get("GEMMA_MODEL", "gemma4:26b")

# Gemma fails with HTTP 200 carrying malformed JSON roughly 1 in 9 (measured over
# a week of prompt generation). Every observed failure succeeded on the next
# attempt, so these retries are IMMEDIATE — a local model has no rate limit to
# back off from, unlike the Opus path below.
_GEMMA_ATTEMPTS = 5
_TIMEOUT_S = 900.0

# The vendored schema's top-level keys. The template forbids adding or omitting
# keys, and Gemma has emitted `scene_imagination` — which belongs to the report's
# Appendix B.1 template, not this one. Checked in both directions.
CANONICAL_KEYS = frozenset({
    "actions", "aesthetics", "artistic_style", "aspect_ratio", "audio_description",
    "background_setting", "cinematography", "context", "duration", "fps",
    "lighting", "resolution", "segments", "style_medium", "subjects",
    "temporal_caption", "text_and_signage_elements", "transitions",
})


def validate_structured(data: dict) -> None:
    """Raise ValueError unless `data` is a well-formed structured prompt.

    Stricter than the old `"subjects" in data` check, because Gemma's failures are
    schema-shaped as well as syntax-shaped: it has added keys the template forbids
    and, at low max_tokens, returned empty content with a populated `reasoning`
    field. Both must be caught here so the caller can retry.
    """
    keys = set(data)
    missing, extra = CANONICAL_KEYS - keys, keys - CANONICAL_KEYS
    if missing:
        raise ValueError(f"missing keys: {sorted(missing)}")
    if extra:
        raise ValueError(f"extra keys (template forbids): {sorted(extra)}")
    if not isinstance(data.get("subjects"), list) or not data["subjects"]:
        raise ValueError("subjects empty or not a list")
    for field in ("temporal_caption", "audio_description"):
        if not str(data.get(field) or "").strip():
            raise ValueError(f"{field} empty")

# Errors worth retrying: transient overload / rate-limit / server-side blip.
# Everything else (400, 413, other 4xx) is deterministic — retrying won't help.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 529})
_MAX_ATTEMPTS = 3
_RETRY_DELAY = 30.0  # seconds between attempts (fixed, not exponential — see Story 014)

_client: AsyncAnthropic | None = None


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()  # key from ANTHROPIC_API_KEY
    return _client


# ---------------------------------------------------------------------------
# Image helpers (Story 6)
# ---------------------------------------------------------------------------

_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8", "image/jpeg"),
    (b"\x89PNG", "image/png"),
    (b"RIFF", "image/webp"),  # WebP: RIFF????WEBP — prefix is enough
]


def _detect_media_type(data: bytes) -> str:
    for magic, mime in _MAGIC:
        if data[: len(magic)] == magic:
            return mime
    return "image/jpeg"  # safe fallback; Anthropic will reject if truly wrong


def _labelled_images(images: list[bytes], labels: list[str] | None) -> list[dict]:
    """Interleave each still with a caption naming its position and timestamp."""
    out: list[dict] = []
    for i, b in enumerate(images):
        if labels and i < len(labels):
            out.append({"type": "text", "text": labels[i]})
        out.append(_image_block(b))
    return out


def _image_block(image_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": _detect_media_type(image_bytes),
            "data": base64.standard_b64encode(image_bytes).decode("ascii"),
        },
    }


# ---------------------------------------------------------------------------
# Size parsing and output param pinning (Story 7)
# ---------------------------------------------------------------------------

# Schema-allowed duration labels (from upsampler_schema.json duration enum).
# At 24 fps this corresponds to a maximum of 240 frames (10 s × 24).
_ALLOWED_DURATIONS = frozenset(f"{s}s" for s in range(2, 11))  # '2s'..'10s'


def tier_for_size(size: str) -> str | None:
    """'832x480' → '480'. None if the size is not in RESOLUTION_RATIO_DICT."""
    try:
        w_str, h_str = size.lower().split("x")
        w, h = int(w_str), int(h_str)
    except (ValueError, AttributeError):
        return None
    for tier, aspects in RRD.items():
        for dims in aspects.values():
            if dims["W"] == w and dims["H"] == h:
                return tier
    return None


def _parse_size(
    size: str, num_frames: int, fps: int, condition_frames: int = 0
) -> tuple[str, str, str]:
    """Reverse-lookup size string e.g. '720x1280' → (tier, aspect_ratio, duration_label).

    Returns ('720', '9,16', '7s') for size='720x1280', num_frames=189, fps=24.
    Raises ValueError (→ HTTP 400) if size is not in RRD or duration is out of schema range.

    `condition_frames` is the V2V conditioning window. Duration describes the
    **generated continuation**, not the whole output — NVIDIA's V2V contract does
    the same (Physics-IQ conditions on 3 s, predicts 5 s, pins duration="0:05").
    Left at 0 the I2V behaviour is unchanged: duration is measured over the total.
    """
    try:
        w_str, h_str = size.lower().split("x")
        w, h = int(w_str), int(h_str)
    except ValueError:
        raise ValueError(f"size must be WxH (e.g. '720x1280'), got: {size!r}")
    generated_frames = num_frames - condition_frames
    for tier, aspects in RRD.items():
        for aspect, dims in aspects.items():
            if dims["W"] == w and dims["H"] == h:
                duration = f"{int(generated_frames / fps)}s"
                if duration not in _ALLOWED_DURATIONS:
                    _max_dur = max(_ALLOWED_DURATIONS, key=lambda s: int(s[:-1]))
                    span = (
                        f"{generated_frames} generated frames "
                        f"({num_frames} total − {condition_frames} conditioning)"
                        if condition_frames
                        else f"num_frames={num_frames}"
                    )
                    raise ValueError(
                        f"{span} at fps={fps} → duration '{duration}', "
                        f"which is outside the schema's allowed set ('2s'–{_max_dur!r}). "
                        f"Maximum is {_max_dur} ({int(fps * int(_max_dur[:-1]))} generated frames at {fps} fps)."
                    )
                return tier, aspect, duration
    supported = ", ".join(
        f"{d['W']}x{d['H']}" for aspects in RRD.values() for d in aspects.values()
    )
    raise ValueError(f"size {size!r} not in RESOLUTION_RATIO_DICT. Supported: {supported}")


def _pin_output_params(
    data: dict, *, resolution: str, aspect_ratio: str, duration: str, fps: int
) -> dict:
    """Overwrite the four output fields with deterministic values from the request."""
    pair = RRD[resolution][aspect_ratio]  # already validated by _parse_size
    data["resolution"] = {"H": pair["H"], "W": pair["W"]}
    data["aspect_ratio"] = aspect_ratio
    data["duration"] = duration  # same value used in the prompt — single source of truth
    data["fps"] = fps
    return data


def _extract_json(text: str) -> dict:
    """Strip the ```json fence and parse. Raises ValueError on any parse or type failure."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = match.group(1) if match else text.strip()
    data = json.loads(raw)  # raises json.JSONDecodeError on bad JSON
    if not isinstance(data, dict):
        raise ValueError(f"expected dict, got {type(data).__name__}")
    return data


# temperature/top_p/top_k from NVIDIA's PromptUpsamplerConfig are not accepted
# by claude-opus-4-8 (BUG_001). max_tokens retained; model uses its own defaults.
_SAMPLING_PARAMS = {"max_tokens": 8192}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def frame_labels(count: int, condition_frames: int, fps: int) -> list[str]:
    """Per-still captions naming position and timestamp within the window.

    Without these the reasoner has to infer temporal order from message position
    alone. Stating it costs a handful of tokens and removes the guess — the whole
    point of showing several frames is to convey motion, which is worthless if
    their order is ambiguous. t=0 is the start of the conditioning window; the
    last still sits at its end, which is where the continuation begins.
    """
    if count < 1:
        return []
    span = max(0, condition_frames - 1) / fps
    if count == 1:
        return [f"conditioning frame 1 of 1, t={span:.2f}s (final frame before the continuation)"]
    out = []
    for i in range(count):
        t = span * i / (count - 1)
        note = " (final frame before the continuation)" if i == count - 1 else ""
        out.append(f"conditioning frame {i + 1} of {count}, t={t:.2f}s{note}")
    return out


async def upsample(
    prompt: str,
    image_bytes: bytes | list[bytes],
    size: str,
    num_frames: int,
    fps: int,
    generate_sound: bool,
    reasoner: str = "gemma",
    mode: str = "i2v",
    condition_frames: int = 0,
) -> tuple[str | None, str | None, dict | None]:
    """Expand a prose brief into the structured JSON prompt.

    `image_bytes` is one still on the I2V path, or an ordered list of stills
    sampled from the conditioning window on the V2V path.

    Returns (json_string, None, meta) on success, or (None, reason, None/meta)
    on failure — the caller falls back to the prose path and reports the reason
    to the client. Special reason values:
      'invalid_size' → caller should HTTP 400
    All other reasons → prose fallback. Unlike the removed AEON path, an
    unreachable local reasoner does NOT 503 — it degrades to prose, because
    Ollama being down should not fail a render the engine can still perform.

    meta always includes 'reasoner' and 'upsample_attempts'.
    """
    if reasoner == "opus" and not available():
        return None, "no_api_key", None

    # On V2V the JSON's `duration` describes the CONTINUATION, not the whole
    # output. NVIDIA's own V2V contract does this: the Physics-IQ protocol
    # conditions on 3 s, predicts 5 s, and the template pins duration="0:05".
    # Describing the total would tell the model to fit the future into a window
    # that is partly already spent.
    duration_frames = num_frames - condition_frames if mode == "v2v" else num_frames

    try:
        resolution, aspect_ratio, duration = _parse_size(size, duration_frames, fps)
    except ValueError as exc:
        print(f"upsampler: invalid size — {exc}", flush=True)
        return None, "invalid_size", None

    user_text = build_upsampler_prompt(
        prompt, resolution=resolution, aspect_ratio=aspect_ratio,
        duration=duration, fps=fps, mode=mode,
    )

    images = image_bytes if isinstance(image_bytes, list) else [image_bytes]
    # Only V2V shows multiple stills; a lone I2V frame needs no ordering caption.
    labels = frame_labels(len(images), condition_frames, fps) if mode == "v2v" else []

    if reasoner == "opus":
        return await _upsample_opus(
            user_text, images, generate_sound,
            resolution, aspect_ratio, duration, fps, labels,
        )
    return await _upsample_gemma(
        user_text, images, generate_sound,
        resolution, aspect_ratio, duration, fps, labels,
    )


# ---------------------------------------------------------------------------
# Opus path (Anthropic API)
# ---------------------------------------------------------------------------

async def _upsample_opus(
    user_text: str,
    images: list[bytes],
    generate_sound: bool,
    resolution: str,
    aspect_ratio: str,
    duration: str,
    fps: int,
    labels: list[str] | None = None,
) -> tuple[str | None, str | None, dict | None]:
    attempt = 0
    message = None
    latency_s = 0.0
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            message = await _get_client().with_options(timeout=120.0).messages.create(
                model=MODEL,
                system="You are a helpful assistant.",  # framework SYSTEM_MESSAGE verbatim
                messages=[
                    {
                        "role": "user",
                        "content": [
                            # Images first (framework order), oldest to newest.
                            # On V2V each is preceded by a caption naming its
                            # position and timestamp so the order is stated
                            # rather than inferred from message position.
                            *_labelled_images(images, labels),
                            {"type": "text", "text": user_text},
                        ],
                    }
                ],
                **_SAMPLING_PARAMS,
            )
            latency_s = round(time.monotonic() - t0, 2)
            break  # success — exit retry loop
        except anthropic.APIStatusError as exc:
            if exc.status_code not in _RETRYABLE_STATUS or attempt == _MAX_ATTEMPTS:
                reason = f"api_error: {type(exc).__name__}: {exc}"
                print(f"upsampler: falling back to prose — {reason}", flush=True)
                return None, reason, {"reasoner": "opus", "upsample_attempts": attempt}
            print(
                f"upsampler opus: attempt {attempt}/{_MAX_ATTEMPTS} failed "
                f"(HTTP {exc.status_code}), retrying in {_RETRY_DELAY:.0f}s",
                flush=True,
            )
            await asyncio.sleep(_RETRY_DELAY)
        except anthropic.APIConnectionError as exc:
            if attempt == _MAX_ATTEMPTS:
                reason = f"api_error: {type(exc).__name__}: {exc}"
                print(f"upsampler: falling back to prose — {reason}", flush=True)
                return None, reason, {"reasoner": "opus", "upsample_attempts": attempt}
            print(
                f"upsampler opus: attempt {attempt}/{_MAX_ATTEMPTS} connection error, "
                f"retrying in {_RETRY_DELAY:.0f}s",
                flush=True,
            )
            await asyncio.sleep(_RETRY_DELAY)
        except Exception as exc:
            reason = f"api_error: {type(exc).__name__}: {exc}"
            print(f"upsampler: falling back to prose — {reason}", flush=True)
            return None, reason, {"reasoner": "opus", "upsample_attempts": attempt}

    if message.stop_reason == "refusal":
        print("upsampler: refusal, falling back to prose", flush=True)
        return None, "refusal", {"reasoner": "opus", "upsample_attempts": attempt}

    text = next((b.text for b in message.content if b.type == "text"), "")
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    meta = {
        "reasoner": "opus",
        "upsample_attempts": attempt,
        "model": MODEL,
        "prompt_sent": user_text,
        "sampling_params": _SAMPLING_PARAMS,
        "raw_response": text,
        "stop_reason": message.stop_reason,
        "usage": usage,
        "latency_s": latency_s,
    }

    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"upsampler: JSON parse failed ({exc}), falling back to prose", flush=True)
        return None, "upsampler_error", meta

    try:
        validate_structured(data)
    except ValueError as exc:
        print(f"upsampler: invalid structure ({exc}), falling back to prose", flush=True)
        return None, "invalid_json", meta

    _pin_output_params(data, resolution=resolution, aspect_ratio=aspect_ratio,
                       duration=duration, fps=fps)
    if not generate_sound:
        data["audio_description"] = ""

    print(
        f"upsampler: ok — {latency_s}s, {attempt} attempt(s), "
        f"{usage['input_tokens']}in/{usage['output_tokens']}out tokens",
        flush=True,
    )
    return json.dumps(data, ensure_ascii=True), None, meta


# ---------------------------------------------------------------------------
# Gemma path (local gemma4:26b via Ollama's OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------


async def _unload_gemma() -> None:
    """Evict the model from memory. Best-effort — never raises.

    Ollama holds a model resident for 5 minutes after the last request by
    default. On unified memory that is not idle capacity: a resident 26B sits in
    the same 121 GiB the engine needs, and has already paged it to swap mid-run.
    Upsampling happens once per clip and denoising takes ~40 min, so there is
    nothing to gain from keeping it warm.

    Sent to the native endpoint, not the OpenAI-compatible one: `keep_alive` is
    not part of the OpenAI schema, and a compat layer is free to drop unknown
    fields silently — which would look identical to success while leaving the
    model loaded.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(f"{GEMMA_URL}/api/generate",
                              json={"model": GEMMA_MODEL, "keep_alive": 0})
    except Exception as exc:  # never fail the request over cleanup
        print(f"upsampler: gemma unload failed ({type(exc).__name__}) — "
              f"model may stay resident ~5 min", flush=True)


async def _upsample_gemma(
    user_text: str,
    images: list[bytes],
    generate_sound: bool,
    resolution: str,
    aspect_ratio: str,
    duration: str,
    fps: int,
    labels: list[str] | None = None,
) -> tuple[str | None, str | None, dict | None]:
    """Upsample with the local model. Retries cover CONTENT failures, not just HTTP.

    The Opus path retries only on transport errors, which is right for an API that
    returned valid JSON 72 of 72 times. Gemma instead fails with a 200 carrying
    malformed JSON, so a parse or schema failure has to be retryable here or every
    such response would fall silently through to prose.
    """
    parts: list[dict] = []
    for i, b in enumerate(images):
        if labels and i < len(labels):
            parts.append({"type": "text", "text": labels[i]})
        parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{_detect_media_type(b)};base64,"
                       f"{base64.standard_b64encode(b).decode('ascii')}"
            },
        })
    payload = {
        "model": GEMMA_MODEL,
        # Gemma is a thinking model: reasoning tokens are drawn from this budget.
        # At 300 the content came back EMPTY while 447 went to a `reasoning`
        # field, so keep this generous and treat empty content as a failure.
        "max_tokens": 8192,
        "stream": False,
        "messages": [{"role": "user", "content": [*parts, {"type": "text", "text": user_text}]}],
    }
    url = f"{GEMMA_URL}/v1/chat/completions"

    last_reason = "upsampler_error"
    text = ""
    contacted = False  # skip the unload call if we never reached Ollama at all
    try:
        for attempt in range(1, _GEMMA_ATTEMPTS + 1):
            t0 = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
                    resp = await client.post(url, json=payload)
                contacted = True
                latency_s = round(time.monotonic() - t0, 2)
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"].get("content") or ""
                if not text.strip():
                    raise ValueError("empty content (thinking tokens consumed the budget?)")
                data = _extract_json(text)
                validate_structured(data)
            except httpx.ConnectError as exc:
                print(f"upsampler: gemma unreachable at {GEMMA_URL} — {exc}", flush=True)
                return None, "gemma_unreachable", {"reasoner": "gemma",
                                                   "upsample_attempts": attempt}
            except Exception as exc:
                last_reason = (
                    "invalid_json" if isinstance(exc, (ValueError, json.JSONDecodeError))
                    else f"api_error: {type(exc).__name__}: {exc}"
                )
                print(
                    f"upsampler gemma: attempt {attempt}/{_GEMMA_ATTEMPTS} — "
                    f"{type(exc).__name__}: {str(exc)[:80]}",
                    flush=True,
                )
                continue  # immediate retry: no rate limit to back off from

            _pin_output_params(data, resolution=resolution, aspect_ratio=aspect_ratio,
                               duration=duration, fps=fps)
            if not generate_sound:
                data["audio_description"] = ""
            meta = {
                "reasoner": "gemma",
                "upsample_attempts": attempt,
                "model": GEMMA_MODEL,
                "endpoint": GEMMA_URL,
                "prompt_sent": user_text,
                "raw_response": text,
                "latency_s": latency_s,
            }
            print(f"upsampler: gemma ok — {latency_s}s, {attempt} attempt(s)", flush=True)
            return json.dumps(data, ensure_ascii=True), None, meta

        print(f"upsampler: gemma exhausted {_GEMMA_ATTEMPTS} attempts, falling back to prose",
              flush=True)
        return None, last_reason, {"reasoner": "gemma", "upsample_attempts": _GEMMA_ATTEMPTS,
                                   "raw_response": text}
    finally:
        # After the loop, not between attempts: a retry would otherwise pay a full
        # reload of a 26B model to fix what is usually a JSON formatting slip.
        if contacted:
            await _unload_gemma()
