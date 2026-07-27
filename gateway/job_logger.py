"""Per-job request/response logger.

Writes one JSON file per generation to /logs/jobs/ so the full chain —
original prose prompt → upsampler output → Cosmos job response — can be
inspected and analysed offline.

File naming: {recorded_at}_{job_id}.json  (UTC timestamp first for sort order)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path(os.environ.get("LOG_DIR", "/logs/jobs"))


def write(
    *,
    job_id: str,
    prose_prompt: str,
    size: str,
    num_frames: int,
    num_inference_steps: int,
    generate_sound: bool,
    seed: str,
    upsample: bool,
    mode: str = "i2v",
    image_filename: str | None,
    image_media_type: str | None,
    upsampler_output: str | None,
    upsampler_fallback_reason: str | None,
    upsampler_meta: dict | None,
    engine_form: dict | None,
    cosmos_response: dict,
) -> None:
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = _LOG_DIR / f"{ts}_{job_id}.json"
        record = {
            "job_id": job_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "request": {
                "prompt": prose_prompt,
                "size": size,
                "num_frames": num_frames,
                "num_inference_steps": num_inference_steps,
                "generate_sound": generate_sound,
                "seed": seed,
                "upsample": upsample,
                "mode": mode,
                "image_filename": image_filename,
                "image_media_type": image_media_type,
            },
            "upsampler": {
                "output": json.loads(upsampler_output) if upsampler_output else None,
                "fallback_reason": upsampler_fallback_reason,
                "api": upsampler_meta,
            },
            "engine_request": engine_form,
            "cosmos": cosmos_response,
        }
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"job_logger: failed to write log for {job_id}: {exc}", flush=True)
