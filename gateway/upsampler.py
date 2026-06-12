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

import json
import os
import re

from anthropic import AsyncAnthropic

MODEL = os.environ.get("UPSAMPLER_MODEL", "claude-opus-4-8")

_client: AsyncAnthropic | None = None


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()  # key from ANTHROPIC_API_KEY
    return _client


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


def _extract_json(text: str) -> dict | None:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def upsample(
    prompt: str,
    image_b64: str,
    image_media_type: str,
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
            max_tokens=16000,
            thinking={"type": "adaptive"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
    except Exception as exc:
        reason = f"api_error: {type(exc).__name__}: {exc}"
        print(f"upsampler: falling back to prose — {reason}", flush=True)
        return None, reason

    if message.stop_reason == "refusal":
        print("upsampler: refusal, falling back to prose", flush=True)
        return None, "refusal"

    text = next((b.text for b in message.content if b.type == "text"), "")
    data = _extract_json(text)
    if not data or "scene_imagination" not in data:
        print("upsampler: no valid JSON in response, falling back to prose", flush=True)
        return None, "invalid_json"

    # Media controls are deterministic — set them from the request rather
    # than trusting the LLM to copy them (it sometimes leaves the template's
    # "Per task constraints" placeholders).
    data["duration"] = _duration_mss(num_frames, fps)
    data["fps"] = fps
    data["aspect_ratio"] = _aspect(width, height)
    data["resolution"] = {"W": width, "H": height}
    if not generate_sound:
        data["audio_description"] = ""

    return json.dumps(data, ensure_ascii=False), None
