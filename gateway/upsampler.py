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


# Appendix B.1 output template (video), verbatim structure.
_OUTPUT_TEMPLATE = (
    '{"scene_imagination":"...","temporal_caption":"...","audio_description":"...",'
    '"subjects":[...],"background_setting":"...","lighting":{...},'
    '"aesthetics":{...},"cinematography":{...},"style_medium":"...",'
    '"artistic_style":"...","context":"...","actions":[...],'
    '"text_and_signage_elements":[...],"segments":[...],"transitions":[...],'
    '"resolution":"Per task constraints","aspect_ratio":"Per task constraints",'
    '"duration":"Per task constraints","fps":"Per task constraints"}'
)


def _duration_mss(num_frames: int, fps: int) -> str:
    seconds = round(num_frames / fps)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _aspect(width: int, height: int) -> str:
    # Template uses nominal labels (NVIDIA's own example pairs "9,16" with 480x832).
    if height > width:
        return "9,16"
    if width > height:
        return "16,9"
    return "1,1"


def build_user_text(
    description: str,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    audio_style: str,
    generate_sound: bool,
) -> str:
    """Assemble the Appendix B.1 I2V upsampler message."""
    duration = _duration_mss(num_frames, fps)
    aspect = _aspect(width, height)

    if not generate_sound:
        audio_constraint = 'Set audio_description to the empty string "" (no audio track will be generated).'
    elif "AUDIO:" in description:
        audio_constraint = (
            "Derive audio_description from the AUDIO direction included in the "
            "video description; do not invent sounds beyond it."
        )
    else:
        house = " ".join(audio_style.split()) if audio_style else ""
        house = house.removeprefix("AUDIO:").strip()  # header is for prose prompts
        audio_constraint = (
            f"audio_description must follow this standing direction: {house}"
            if house
            else "Describe natural ambient sound matching the scene."
        )

    return f"""<instructions>
Prompt upsampler for an image-to-video model. Treat the attached starting frame
as definitive visual ground truth and the text as temporal/action intent.
Produce exactly one fenced JSON object that fully populates the template and
satisfies all constraints.
</instructions>
<video_description>{description}</video_description>
<task_constraints>
1. Write scene_imagination first, anchoring visual facts to the image and
temporal facts to the description.
2. Write temporal_caption second as the timestamped M:SS playback timeline.
3. Write audio_description third, aligned with the visual beats when possible.
   {audio_constraint}
4. Copy exactly: duration="{duration}", fps={fps}, aspect_ratio="{aspect}",
resolution={{"W":{width},"H":{height}}}.
5. Use only M:SS timing and keep all timed fields within duration.
6. Ensure the first segment and earliest actions match the image at t=0.
7. Preserve concrete facts from both the image and the description.
</task_constraints>
<output_json_template>
{_OUTPUT_TEMPLATE}
</output_json_template>"""


def _extract_json(text: str) -> dict:
    """Strip the ```json fence and parse. Raises ValueError on any parse or type failure."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = match.group(1) if match else text.strip()
    data = json.loads(raw)  # raises json.JSONDecodeError on bad JSON
    if not isinstance(data, dict):
        raise ValueError(f"expected dict, got {type(data).__name__}")
    return data


async def upsample(
    prompt: str,
    image_bytes: bytes,
    width: int,
    height: int,
    num_frames: int,
    fps: int,
    audio_style: str,
    generate_sound: bool,
) -> tuple[str | None, str | None]:
    """Expand a prose brief into the structured JSON prompt.

    Returns (json_string, None) on success, or (None, reason) on any
    failure — the caller falls back to the prose path and reports the
    reason to the client.
    """
    if not available():
        return None, "no_api_key"

    user_text = build_user_text(
        prompt, width, height, num_frames, fps, audio_style, generate_sound
    )
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
            # Framework PromptUpsamplerConfig defaults. temperature + top_p + top_k
            # together is intentional — matches what NVIDIA validated.
            temperature=0.7,
            top_p=0.8,
            top_k=20,
            max_tokens=8192,
        )
    except Exception as exc:
        reason = f"api_error: {type(exc).__name__}: {exc}"
        print(f"upsampler: falling back to prose — {reason}", flush=True)
        return None, reason

    if message.stop_reason == "refusal":
        print("upsampler: refusal, falling back to prose", flush=True)
        return None, "refusal"

    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"upsampler: JSON parse failed ({exc}), falling back to prose", flush=True)
        return None, "upsampler_error"

    if "scene_imagination" not in data:
        print("upsampler: missing expected fields, falling back to prose", flush=True)
        return None, "invalid_json"

    # Media controls are deterministic — set them from the request rather
    # than trusting the LLM to copy them (it sometimes leaves the template's
    # "Per task constraints" placeholders). Replaced by _pin_output_params in Story 7.
    data["duration"] = _duration_mss(num_frames, fps)
    data["fps"] = fps
    data["aspect_ratio"] = _aspect(width, height)
    data["resolution"] = {"W": width, "H": height}
    if not generate_sound:
        data["audio_description"] = ""

    return json.dumps(data, ensure_ascii=False), None
