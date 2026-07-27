"""cosmos-gateway: the canonical request layer for Cosmos 3 on this box.

This repo owns what gets sent to the Cosmos container. Clients (the pipeline)
send creative intent — image, prompt, size, length — and the gateway applies
the house contract before forwarding to vLLM-Omni:

- negative prompt from data/neg.json (NVIDIA Appendix B.6, benchmark-tuned)
- tuned sampling params (Table 21): guidance 6.0, flow_shift 10.0, fps 24
- guardrails/template extra_params, correct field names
  (generate_sound/sound_duration — never enable_audio)

Endpoints:
    POST   /generate            multipart: image OR video (file), prompt,
                                [size=720x1280, frames=189,
                                 steps=35, sound=true,
                                 seed]                  -> upstream job JSON
                                image -> image-to-video, video -> video-to-
                                video (continuation). Exactly one is required;
                                the populated field selects the mode.
    GET    /jobs/{id}           status; merges REAL progress from the
                                progress sidecar when fresh + id-matched
    GET    /jobs/{id}/content   streams the MP4
    DELETE /jobs/{id}           passthrough cancel/delete
    GET    /health              gateway + upstream liveness

data/ is mounted read-only from the repo, so the repo working copy is
consumed directly — git is the deploy mechanism for the contract.
"""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import job_logger
import upsampler
import video as video_util

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
_EXTRA_PARAMS_BASE = {
    "guardrails": False,
    "use_resolution_template": False,
    "use_duration_template": False,
}
# Frozen string for the I2V path — byte-identical to what shipped before V2V.
EXTRA_PARAMS = json.dumps(_EXTRA_PARAMS_BASE)

# Default conditioning window when the client doesn't ask: the engine's own
# (0, 1) / 5-pixel-frame default. 0.2 s at 24 fps.
_DEFAULT_CONDITION_SECONDS = 0.2

# Stills handed to the reasoner on the V2V path. Enough to convey direction and
# speed of motion rather than a single pose; more would cost tokens for little
# extra signal at 2 s of source.
_V2V_PROMPT_FRAMES = 5

# End-to-end time model for the elapsed-time progress estimate. vLLM-Omni
# never moves the `progress` field during a render and the tqdm log bar only
# flushes at the end (docs/api.md), so a *moving* bar must come from
# elapsed/expected. expected = denoise + tail, both scaling with the job's
# pixel·frame volume (W*H*frames):
#
#   denoise = steps * REF_S_PER_STEP * (vol/REF_VOLUME)**VOLUME_EXP
#   tail    = REF_TAIL_S * (vol/REF_VOLUME)              [VAE decode+audio+encode]
#
# Recalibrated 2026-07-27 from 24 measured renders at the reference volume
# (832x480x189, 35 steps, sound on): median 526 s end-to-end, range 518–609 s.
# The sidecar measured 12.9 s/step, confirming the 13.02 denoise anchor, which
# leaves tail = 526 − 35·12.9 ≈ 74 s. The previous _REF_TAIL_S of 423 s was
# never measured — it came from subtracting 50·13.02 from a single 50-step job's
# 1073.8 s, and overstated the tail by 5.7x, making every ETA wildly pessimistic.
# VOLUME_EXP=1.6 remains validated only by the ~46 s/step observation at
# 704x1280x189; it is untested at a third volume.
_REF_VOLUME = 832 * 480 * 189
_REF_S_PER_STEP = 13.02
_VOLUME_EXP = 1.6
_REF_TAIL_S = 74.0
_DEFAULT_STEPS = 50  # used if the job's params were lost (gateway restart)
_DEFAULT_FRAMES = 189


def _parse_size(size) -> tuple[int | None, int | None]:
    try:
        w, h = str(size).lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None, None


def _expected_seconds(width: int, height: int, num_frames: int, steps: int) -> float:
    vol = max(1, width * height * num_frames)
    scale = vol / _REF_VOLUME
    denoise = steps * _REF_S_PER_STEP * scale**_VOLUME_EXP
    tail = _REF_TAIL_S * scale
    return denoise + tail


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


_VALID_REASONERS = ("opus", "aeon")

# The WAN VAE compresses 4 pixel frames into 1 latent frame, so a video's frame
# count must be 4k+1 for the encoded conditioning latent to match the noise
# tensor. On the V2V path the engine enforces this with a hard
# "Cosmos3 V2V latent shape mismatch" (pipeline_cosmos3.py _prepare_latents_v2v);
# catching it here turns an hour-deep 500 into an immediate 400.
_VAE_TEMPORAL_COMPRESSION = 4


def _is_valid_frame_count(frames: int) -> bool:
    return (frames - 1) % _VAE_TEMPORAL_COMPRESSION == 0


def _nearest_frame_counts(frames: int) -> tuple[int, int]:
    lo = ((frames - 1) // _VAE_TEMPORAL_COMPRESSION) * _VAE_TEMPORAL_COMPRESSION + 1
    return lo, lo + _VAE_TEMPORAL_COMPRESSION


# Per-resolution frame ceilings (technical report Fig. 10): 256p and 480p allow
# up to 400 frames, 720p up to 300. The previous blanket min(300, …) applied the
# 720p limit everywhere, which blocked 3 s of conditioning plus a full 10 s of new
# video at 480p (313 frames) for no reason. 768p is unlisted; treat it like 720p.
_FRAME_CEILINGS = {"256": 400, "480": 400, "720": 300, "768": 300}
_FRAME_CEILING_FALLBACK = 300
_FRAME_FLOOR = 5


def _frame_ceiling(size: str) -> int:
    return _FRAME_CEILINGS.get(upsampler.tier_for_size(size), _FRAME_CEILING_FALLBACK)


@app.post("/generate")
async def generate(
    image: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    prompt: str = Form(...),
    size: str = Form("720x1280"),
    frames: int = Form(189),
    steps: int = Form(35),
    sound: bool = Form(True),
    seed: int | None = Form(None),
    upsample: bool = Form(True),
    reasoner: str = Form("opus"),
    condition_seconds: float | None = Form(None),
):
    if reasoner not in _VALID_REASONERS:
        raise HTTPException(422, f"reasoner must be one of {list(_VALID_REASONERS)}, got {reasoner!r}")

    # Mode dispatch (STORY_017). The engine has no V2V flag — it decodes
    # input_reference and branches on what it got (image -> I2V, video -> V2V,
    # pipeline_cosmos3.py: `is_v2v = video_tensor is not None`). So the mode is
    # selected by *which* file field the client populated, not by a boolean; a
    # flag could only ever assert what the bytes already determine.
    if bool(image) == bool(video):
        detail = (
            "send exactly one of image= (image-to-video) or video= (video-to-video); "
            + ("both were supplied" if image else "neither was supplied")
        )
        raise HTTPException(400, detail)
    mode = "i2v" if image else "v2v"
    media = image or video

    if mode == "i2v" and condition_seconds is not None:
        raise HTTPException(
            400, "condition_seconds applies to video-to-video only; it is meaningless with image="
        )
    if condition_seconds is None:
        condition_seconds = _DEFAULT_CONDITION_SECONDS
    elif condition_seconds <= 0:
        raise HTTPException(400, f"condition_seconds must be positive, got {condition_seconds}")

    # The conditioning window is pure arithmetic, so resolve it before validation:
    # on the V2V path the duration check measures the *generated* span, which needs
    # this number. The clip itself is not touched until later.
    indexes: tuple[int, ...] = ()
    condition_frames = 0
    if mode == "v2v":
        indexes, condition_frames = video_util.condition_window(condition_seconds, FPS)

    frames = max(_FRAME_FLOOR, min(_frame_ceiling(size), frames))

    # Before the duration check, so "nothing left to generate" beats a confusing
    # complaint about a 0s duration.
    if mode == "v2v" and condition_frames >= frames:
        raise HTTPException(
            400,
            f"condition_seconds={condition_seconds} consumes {condition_frames} of the "
            f"{frames} requested frames, leaving nothing to generate; lower "
            f"condition_seconds or raise frames",
        )

    # V2V only, deliberately: the same 4k+1 rule governs the I2V latent maths,
    # but no I2V request has ever been rejected for it and this story must not
    # change the I2V path. Widening it needs an empirical check first.
    if mode == "v2v" and not _is_valid_frame_count(frames):
        lo, hi = _nearest_frame_counts(frames)
        raise HTTPException(
            400,
            f"frames must be of the form 4k+1 for video-to-video (the VAE compresses "
            f"4 pixel frames into 1 latent frame); got {frames}, nearest valid are {lo} and {hi}",
        )

    if steps not in (35, 50):
        raise HTTPException(400, f"steps must be 35 (default) or 50 (high quality), got {steps}")

    # Validate size + duration unconditionally (BUG-002: was only checked on
    # the upsampled path). Single source of truth: upsampler._parse_size.
    try:
        upsampler._parse_size(size, frames, FPS, condition_frames)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    media_bytes = await media.read()
    media_media_type = media.content_type or ("image/png" if mode == "i2v" else "video/mp4")

    # V2V: trim the upload to the conditioning window. The window is taken from
    # the *end* of the clip — the pipeline chains clips, so clip 2 conditions on
    # clip 1's final seconds. See gateway/video.py for why this lives here and
    # not in the engine (BUG_003) or the client.
    generated_frames = None
    extra_params = EXTRA_PARAMS
    if mode == "v2v":
        try:
            media_bytes, _source_frames, _ = video_util.prepare_tail(media_bytes, condition_frames)
        except video_util.ClipError as exc:
            raise HTTPException(400, str(exc))
        generated_frames = frames - condition_frames
        extra_params = json.dumps(
            {
                **_EXTRA_PARAMS_BASE,
                "condition_frame_indexes_vision": ",".join(str(i) for i in indexes),
            }
        )

    prompt_source = "prose"
    fallback_reason = "disabled_by_request"  # default when upsample=false

    # Structured-prompt upgrade path (tech report §6.3.2): expand the prose
    # brief into the Appendix A JSON via the upsampler. Any failure falls
    # back to the prose path below, with the reason reported to the client.
    full_prompt = None
    upsampler_meta = None
    if upsample:
        # Opus cannot read video, so V2V shows it stills sampled from the same
        # window the engine conditions on (STORY_019) — sampling the original
        # upload instead would describe motion the model never sees.
        if mode == "v2v":
            try:
                reasoner_input = video_util.sample_frames(media_bytes, _V2V_PROMPT_FRAMES)
            except video_util.ClipError as exc:
                raise HTTPException(400, str(exc))
        else:
            reasoner_input = media_bytes

        structured, fallback_reason, upsampler_meta = await upsampler.upsample(
            prompt=prompt.rstrip(),
            image_bytes=reasoner_input,
            size=size,
            num_frames=frames,
            fps=FPS,
            generate_sound=sound,
            reasoner=reasoner,
            mode=mode,
            condition_frames=condition_frames or 0,
        )
        if fallback_reason == "invalid_size":
            raise HTTPException(400, f"size {size!r} is not supported; see RESOLUTION_RATIO_DICT for valid sizes")
        if fallback_reason == "aeon_unreachable":
            raise HTTPException(503, f"AEON reasoner is not reachable at {upsampler.AEON_URL}; confirm the AEON service is running on Spark 1")
        if structured:
            full_prompt = structured
            prompt_source = "upsampled"

    if full_prompt is None:
        full_prompt = prompt.rstrip()

    # Translate friendly client names → vLLM-Omni wire names.
    form = {
        "prompt": full_prompt,
        "negative_prompt": _read_data("neg.json"),
        "size": size,
        "num_frames": str(frames),
        "num_inference_steps": str(steps),
        "generate_sound": "true" if sound else "false",
        "sound_duration": str(frames / FPS),
        "seed": str(seed if seed is not None else int.from_bytes(os.urandom(4), "big") % (2**31)),
        "extra_params": extra_params,
        **FIXED_PARAMS,
    }
    # One wire field for both modes: the engine sniffs the bytes (image decode
    # first, video decode as fallback) and picks the path from the result.
    files = {
        "input_reference": (media.filename, media_bytes, media_media_type)
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{COSMOS}/v1/videos", data=form, files=files)
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    job = resp.json()
    job["mode"] = mode  # "i2v" (image conditioning) | "v2v" (clip continuation)
    # How the output splits. On v2v the first `condition_frames` frames are a VAE
    # round-trip of the source clip's tail — clients chaining clips discard them
    # and concatenate `clip[condition_frames:]`. Null on i2v: nothing to discard.
    job["condition_frames"] = condition_frames if mode == "v2v" else None
    job["generated_frames"] = generated_frames
    job["prompt_source"] = prompt_source  # "upsampled" | "prose"
    # null when upsampled; otherwise why the gateway used the prose defaults:
    # "disabled_by_request" | "no_api_key" | "refusal" | "invalid_json" | "api_error: …"
    job["upsample_fallback_reason"] = None if prompt_source == "upsampled" else fallback_reason
    # The exact structured prompt the upsampler produced and we sent to the
    # engine — echoed for pipeline provenance/viewing (STORY-016). Means "what
    # the upsampler produced" (same as the job-log key): null on the prose path.
    job["upsampler_output"] = full_prompt if prompt_source == "upsampled" else None

    if video_id := job.get("id"):
        while len(_JOB_META) >= _JOB_META_MAX:
            _JOB_META.pop(next(iter(_JOB_META)))
        _JOB_META[video_id] = {
            "mode": mode,
            "condition_frames": job["condition_frames"],
            "generated_frames": generated_frames,
            "prompt_source": job["prompt_source"],
            "upsample_fallback_reason": job["upsample_fallback_reason"],
            "upsampler_output": job["upsampler_output"],
            "reasoner": reasoner,
            # Internal: feed the /jobs elapsed-time progress estimate. Width/
            # height come from the job's reported `size` at poll time (the
            # engine may snap dims), so only steps + frames are kept here.
            "num_inference_steps": steps,
            "num_frames": frames,
        }
        job_logger.write(
            job_id=video_id,
            prose_prompt=prompt,
            size=size,
            num_frames=frames,
            num_inference_steps=steps,
            generate_sound=sound,
            seed=form["seed"],
            upsample=upsample,
            mode=mode,
            condition_frames=job["condition_frames"],
            image_filename=media.filename,
            image_media_type=media_media_type,
            upsampler_output=full_prompt if prompt_source == "upsampled" else None,
            upsampler_fallback_reason=job["upsample_fallback_reason"],
            upsampler_meta=upsampler_meta,
            engine_form=form,
            cosmos_response=job,
        )
    return job


@app.get("/jobs/{video_id}")
async def job_status(video_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{COSMOS}/v1/videos/{video_id}")
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, resp.text)
        status = resp.json()

        # vLLM-Omni never moves `progress` during generation, and the log bar
        # only flushes at the end — so the *moving* bar is an elapsed-time
        # estimate computed here, with the sidecar kept as a terminal "→99"
        # override for the VAE/audio/encode tail.
        if status.get("status") == "in_progress":
            meta = _JOB_META.get(video_id, {})
            width, height = _parse_size(status.get("size"))
            created = status.get("created_at")
            if width and height and created:
                steps = meta.get("num_inference_steps", _DEFAULT_STEPS)
                frames = meta.get("num_frames", _DEFAULT_FRAMES)
                expected = _expected_seconds(width, height, frames, steps)
                elapsed = max(0.0, time.time() - float(created))
                est = min(99, int(elapsed / expected * 100)) if expected > 0 else 0
                # Monotonic + future-proof: if the engine ever reports real
                # progress, the larger value wins.
                status["progress"] = max(int(status.get("progress") or 0), est)
                status["progress_source"] = "estimate"
                status["eta_s"] = round(max(0.0, expected - elapsed), 1)

            # Sidecar terminal/tail signal: its bar only reaches a log consumer
            # once denoise finishes, so a fresh, id-matched step==total means
            # "denoise done, finishing" — pin to 99 over the estimate.
            try:
                p = (await client.get(f"{SIDECAR}/progress", timeout=2)).json()
                fresh = p.get("age_s") is not None and p["age_s"] < 60
                done = p.get("step") and p.get("total") and p["step"] >= p["total"]
                if p.get("video_id") == video_id and fresh and done:
                    status["progress"] = max(int(status.get("progress") or 0), 99)
                    status["progress_source"] = "sidecar"
                    status["eta_s"] = 0.0
            except Exception:
                pass  # sidecar down -> keep the estimate

    # Expose only the client-facing meta fields (not the internal estimator
    # params stored alongside them).
    if meta := _JOB_META.get(video_id):
        status["mode"] = meta.get("mode")
        status["condition_frames"] = meta.get("condition_frames")
        status["generated_frames"] = meta.get("generated_frames")
        status["prompt_source"] = meta.get("prompt_source")
        status["upsample_fallback_reason"] = meta.get("upsample_fallback_reason")
        status["upsampler_output"] = meta.get("upsampler_output")
        status["reasoner"] = meta.get("reasoner")
    return status


@app.delete("/jobs/{video_id}")
async def job_delete(video_id: str, hard: bool = False):
    """Delete a job. With hard=true, also reclaim the GPU.

    A plain delete removes the job record but vLLM-Omni does NOT cancel
    in-flight GPU work — an orphaned render runs to completion and blocks
    the queue. hard=true additionally restarts the engine (via the sidecar,
    which holds the Docker socket) when this job is the one occupying the
    GPU. Costs ~3.5 min of model reload and wipes the engine's in-memory
    job records (any queued jobs vanish). Poll /health until cosmos=true
    before submitting again.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        was_running = False
        if hard:
            # Only restart if this job is plausibly the active render:
            # the oldest in_progress job (single-GPU engine = FIFO).
            try:
                listing = (await client.get(f"{COSMOS}/v1/videos")).json()
                in_prog = sorted(
                    (j for j in listing.get("data", []) if j.get("status") == "in_progress"),
                    key=lambda j: j.get("created_at") or 0,
                )
                was_running = bool(in_prog) and in_prog[0].get("id") == video_id
            except Exception:
                was_running = True  # can't tell -> honor the hard request

        resp = await client.delete(f"{COSMOS}/v1/videos/{video_id}")
        if resp.status_code >= 400 and not hard:
            raise HTTPException(resp.status_code, resp.text)
        out = resp.json() if (resp.content and resp.status_code < 400) else {"deleted": video_id}

        if not hard:
            # Confirm the engine actually dropped the job (soft delete only).
            try:
                check = await client.get(f"{COSMOS}/v1/videos/{video_id}", timeout=5)
                out["confirmed_stopped"] = check.status_code == 404
            except Exception:
                out["confirmed_stopped"] = False

        if hard:
            engine_restarting = False
            engine_down_confirmed = False
            if was_running:
                try:
                    r = await client.post(f"{SIDECAR}/restart-engine", timeout=5)
                    engine_restarting = r.status_code < 400
                except Exception:
                    pass
                if engine_restarting:
                    # The restart is async (sidecar thread → docker restart),
                    # so /health stays green against the still-up old container
                    # for a few seconds. Wait until the engine actually goes
                    # down, so the client's subsequent "poll /health until
                    # cosmos=true" is a true ready signal (not the pre-restart
                    # container answering). Reload then takes ~3.5 min.
                    for _ in range(30):
                        await asyncio.sleep(1)
                        try:
                            h = await client.get(f"{COSMOS}/health", timeout=2)
                            if h.status_code != 200:
                                engine_down_confirmed = True
                                break
                        except Exception:
                            engine_down_confirmed = True
                            break
            out["hard"] = True
            out["engine_restarting"] = engine_restarting
            out["engine_down_confirmed"] = engine_down_confirmed
    return out


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
