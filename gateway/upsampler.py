"""Prompt upsampler — NVIDIA's documented pre-generation step.

Cosmos 3 was trained on structured JSON captions; NVIDIA's production stack
converts user prompts into that format with an LLM upsampler before
generation (technical report §6.3.2; template: Appendix B.1, I2V variant).
This module implements that step with the Anthropic API — the same vendor
NVIDIA used (Claude Opus) — grounding on the seed image per the official
template: "Treat the attached starting frame as definitive visual ground
truth and the text as temporal/action intent."

Failure of any kind returns None and the gateway falls back to the prose
prompt path — upsampling can never block a render.
"""

import base64
import json
import os
import re
import time
from pathlib import Path
from string import Template

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
) -> str:
    """Assemble the official NVIDIA I2V upsampler prompt from vendored template."""
    nl = build_nl_description(
        prompt, resolution=resolution, aspect_ratio=aspect_ratio,
        duration=duration, fps=fps,
    )
    rrd_text = json.dumps(
        {r: {a: {"H": s["H"], "W": s["W"]} for a, s in ad.items()} for r, ad in RRD.items()},
        indent=2,
    )
    return TEMPLATE.substitute(
        intro=I2V_INTRO,
        image_note=I2V_IMAGE_NOTE,
        json_template=SCHEMA,
        nl_description=nl,
        resolution_ratio_dict=rrd_text,
    )

MODEL = os.environ.get("UPSAMPLER_MODEL", "claude-opus-4-8")

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


def _parse_size(size: str, num_frames: int, fps: int) -> tuple[str, str, str]:
    """Reverse-lookup size string e.g. '720x1280' → (tier, aspect_ratio, duration_label).

    Returns ('720', '9,16', '7s') for size='720x1280', num_frames=189, fps=24.
    Raises ValueError (→ HTTP 400) if size is not in RRD or duration is out of schema range.
    """
    try:
        w_str, h_str = size.lower().split("x")
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
                        f"Maximum is {_max_dur} ({int(fps * int(_max_dur[:-1]))} frames at {fps} fps)."
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


async def upsample(
    prompt: str,
    image_bytes: bytes,
    size: str,
    num_frames: int,
    fps: int,
    generate_sound: bool,
) -> tuple[str | None, str | None, dict | None]:
    """Expand a prose brief into the structured JSON prompt.

    Returns (json_string, None, meta) on success, or (None, reason, None) on
    any failure — the caller falls back to the prose path and reports the
    reason to the client. The special reason 'invalid_size' signals that
    the caller should return HTTP 400 rather than fall back to prose.

    meta contains the full Anthropic API request/response details for logging.
    It is None whenever the API call was not made or not reached.
    """
    if not available():
        return None, "no_api_key", None

    try:
        resolution, aspect_ratio, duration = _parse_size(size, num_frames, fps)
    except ValueError as exc:
        print(f"upsampler: invalid size — {exc}", flush=True)
        return None, "invalid_size", None

    user_text = build_upsampler_prompt(
        prompt, resolution=resolution, aspect_ratio=aspect_ratio,
        duration=duration, fps=fps,
    )
    t0 = time.monotonic()
    try:
        client = _get_client()
        message = await client.with_options(timeout=120.0).messages.create(
            model=MODEL,
            system="You are a helpful assistant.",  # framework SYSTEM_MESSAGE verbatim
            messages=[
                {
                    "role": "user",
                    "content": [
                        _image_block(image_bytes),  # image first (framework order)
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
            **_SAMPLING_PARAMS,
        )
    except Exception as exc:
        reason = f"api_error: {type(exc).__name__}: {exc}"
        print(f"upsampler: falling back to prose — {reason}", flush=True)
        return None, reason, None

    latency_s = round(time.monotonic() - t0, 2)

    if message.stop_reason == "refusal":
        print("upsampler: refusal, falling back to prose", flush=True)
        return None, "refusal", None

    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"upsampler: JSON parse failed ({exc}), falling back to prose", flush=True)
        return None, "upsampler_error", None

    if "subjects" not in data:
        print("upsampler: missing expected fields, falling back to prose", flush=True)
        return None, "invalid_json", None

    _pin_output_params(data, resolution=resolution, aspect_ratio=aspect_ratio,
                       duration=duration, fps=fps)
    if not generate_sound:
        data["audio_description"] = ""

    meta = {
        "model": MODEL,
        "prompt_sent": user_text,
        "sampling_params": _SAMPLING_PARAMS,
        "raw_response": text,
        "stop_reason": message.stop_reason,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
        "latency_s": latency_s,
    }
    print(
        f"upsampler: ok — {latency_s}s, "
        f"{meta['usage']['input_tokens']}in/{meta['usage']['output_tokens']}out tokens",
        flush=True,
    )
    return json.dumps(data, ensure_ascii=True), None, meta
