"""cosmos-gateway: the canonical request layer for Cosmos 3 on this box.

This repo owns what gets sent to the Cosmos container. Clients (the pipeline)
send creative intent — image, prompt, size, length — and the gateway applies
the house contract before forwarding to vLLM-Omni:

- negative prompt from data/neg.json (NVIDIA Appendix B.6, benchmark-tuned)
- audio house style from data/audio.txt appended to the prompt
  (ambient only, no dialogue) whenever sound is on
- tuned sampling params (Table 21): guidance 6.0, flow_shift 10.0, fps 24
- guardrails/template extra_params, correct field names
  (generate_sound/sound_duration — never enable_audio)

Endpoints:
    POST   /generate            multipart: input_reference (file), prompt,
                                [size=720x1280, num_frames=189,
                                 num_inference_steps=50, generate_sound=true,
                                 seed]                  -> upstream job JSON
    GET    /jobs/{id}           status; merges REAL progress from the
                                progress sidecar when fresh + id-matched
    GET    /jobs/{id}/content   streams the MP4
    DELETE /jobs/{id}           passthrough cancel/delete
    GET    /health              gateway + upstream liveness

data/ is mounted read-only from the repo, so the repo working copy is
consumed directly — git is the deploy mechanism for the contract.
"""

import base64
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import upsampler

COSMOS = os.environ.get("COSMOS_URL", "http://cosmos3:8000")
SIDECAR = os.environ.get("SIDECAR_URL", "http://progress:8001")
DATA = Path(os.environ.get("DATA_DIR", "/data"))

FPS = 24
FIXED_PARAMS = {
    "guidance_scale": "6.0",
    "flow_shift": "10.0",
    "fps": str(FPS),
    "max_sequence_length": "4096",
}
EXTRA_PARAMS = json.dumps(
    {"guardrails": False, "use_resolution_template": False, "use_duration_template": False}
)

app = FastAPI(title="cosmos-gateway")

# Per-job prompt provenance, merged into /jobs/{id} responses so pollers see
# it too (in-memory; lost on gateway restart — submit response is canonical).
_JOB_META: dict[str, dict] = {}
_JOB_META_MAX = 256


def _read_data(name: str) -> str:
    path = DATA / name
    return path.read_text().strip() if path.exists() else ""


@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            upstream = (await client.get(f"{COSMOS}/health")).status_code == 200
        except Exception:
            upstream = False
    return {"gateway": "ok", "cosmos": upstream}


@app.post("/generate")
async def generate(
    input_reference: UploadFile = File(...),
    prompt: str = Form(...),
    size: str = Form("720x1280"),
    num_frames: int = Form(189),
    num_inference_steps: int = Form(50),
    generate_sound: bool = Form(True),
    seed: int | None = Form(None),
    upsample: bool = Form(True),
):
    num_frames = max(5, min(300, num_frames))
    image_bytes = await input_reference.read()
    image_media_type = input_reference.content_type or "image/png"
    audio_style = _read_data("audio.txt")
    prompt_source = "prose"
    fallback_reason = "disabled_by_request"  # default when upsample=false

    # Structured-prompt upgrade path (tech report §6.3.2): expand the prose
    # brief into the Appendix A JSON via the upsampler. Any failure falls
    # back to the prose path below, with the reason reported to the client.
    full_prompt = None
    if upsample:
        try:
            width_s, height_s = size.lower().split("x")
            width, height = int(width_s), int(height_s)
        except ValueError:
            raise HTTPException(400, f"invalid size: {size!r} (expected WxH)")
        structured, fallback_reason = await upsampler.upsample(
            prompt=prompt.rstrip(),
            image_b64=base64.standard_b64encode(image_bytes).decode(),
            image_media_type=image_media_type,
            width=width,
            height=height,
            num_frames=num_frames,
            fps=FPS,
            audio_style=audio_style,
            generate_sound=generate_sound,
        )
        if structured:
            full_prompt = structured
            prompt_source = "upsampled"

    if full_prompt is None:
        full_prompt = prompt.rstrip()
        if generate_sound and audio_style and "AUDIO:" not in full_prompt:
            full_prompt += "\n\n" + audio_style

    form = {
        "prompt": full_prompt,
        "negative_prompt": _read_data("neg.json"),
        "size": size,
        "num_frames": str(num_frames),
        "num_inference_steps": str(num_inference_steps),
        "generate_sound": "true" if generate_sound else "false",
        "sound_duration": str(num_frames / FPS),
        "seed": str(seed if seed is not None else int.from_bytes(os.urandom(4), "big") % (2**31)),
        "extra_params": EXTRA_PARAMS,
        **FIXED_PARAMS,
    }
    files = {
        "input_reference": (input_reference.filename, image_bytes, image_media_type)
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{COSMOS}/v1/videos", data=form, files=files)
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    job = resp.json()
    job["prompt_source"] = prompt_source  # "upsampled" | "prose"
    # null when upsampled; otherwise why the gateway used the prose defaults:
    # "disabled_by_request" | "no_api_key" | "refusal" | "invalid_json" | "api_error: …"
    job["upsample_fallback_reason"] = None if prompt_source == "upsampled" else fallback_reason

    if video_id := job.get("id"):
        while len(_JOB_META) >= _JOB_META_MAX:
            _JOB_META.pop(next(iter(_JOB_META)))
        _JOB_META[video_id] = {
            "prompt_source": job["prompt_source"],
            "upsample_fallback_reason": job["upsample_fallback_reason"],
        }
    return job


@app.get("/jobs/{video_id}")
async def job_status(video_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{COSMOS}/v1/videos/{video_id}")
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, resp.text)
        status = resp.json()

        # vLLM-Omni never updates `progress` during generation; merge the real
        # value from the log-parsing sidecar when it's fresh and id-matched.
        if status.get("status") == "in_progress":
            try:
                p = (await client.get(f"{SIDECAR}/progress", timeout=2)).json()
                fresh = p.get("age_s") is not None and p["age_s"] < 60
                if p.get("video_id") == video_id and fresh and p.get("percent") is not None:
                    pct = p["percent"]
                    if p.get("step") == p.get("total") and not p.get("active"):
                        pct = 99  # denoise done, VAE/audio/encode tail
                    status["progress"] = max(int(status.get("progress") or 0), min(99, pct))
                    status["progress_source"] = "sidecar"
                    status["eta_s"] = p.get("eta_s")
            except Exception:
                pass  # sidecar down -> serve upstream status unmodified

    if meta := _JOB_META.get(video_id):
        status.update(meta)
    return status


@app.delete("/jobs/{video_id}")
async def job_delete(video_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(f"{COSMOS}/v1/videos/{video_id}")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json() if resp.content else {"deleted": video_id}


@app.get("/jobs/{video_id}/content")
async def job_content(video_id: str):
    client = httpx.AsyncClient(timeout=None)
    req = client.build_request("GET", f"{COSMOS}/v1/videos/{video_id}/content")
    resp = await client.send(req, stream=True)
    if resp.status_code >= 400:
        await resp.aclose()
        await client.aclose()
        raise HTTPException(resp.status_code, "upstream error fetching content")

    async def stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(stream(), media_type=resp.headers.get("content-type", "video/mp4"))
