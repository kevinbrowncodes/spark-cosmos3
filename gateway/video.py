"""Conditioning-clip preparation for the V2V path (STORY_018).

The pipeline chains clips: clip 2 conditions on the *last* two seconds of clip 1.
The engine cannot do that on its own. It conditions on the first frames of
whatever it decodes, and the knob meant for this — `condition_video_keep:
"last"` — is dead over HTTP (BUG_003): the server truncates to the first N
frames at decode time, before the setting is ever read. So the gateway trims
here and forwards a clip that already *begins* where conditioning should start.

Two rules this module exists to enforce:

1. **Count frames by decoding, exactly as the engine does.** vLLM-Omni's
   `_decode_video_bytes` walks `container.decode(video=0)`; container metadata
   such as `nb_frames` is frequently absent or wrong. Trusting metadata would let
   a too-short clip past the guard, and that failure is silent — the engine's
   `_prepare_latents_v2v` pads by repeating the final frame, so the model is
   handed a confident signal that the scene has stopped moving and duly
   generates a frozen scene.

2. **Reject anything that is not 24 fps.** The engine's decode is frame-count
   based with no timestamp or frame-rate awareness, so a 30 fps clip silently
   becomes slow motion with a discontinuity at the seam.
"""

import io
from collections import deque
from fractions import Fraction

import av

FPS = 24
VAE_TEMPORAL_COMPRESSION = 4

# The engine's own floor: condition_frame_indexes_vision defaults to (0, 1) —
# 5 pixel frames, the T_cond=2 recipe Cosmos 3 pre-trained V2V on. A smaller
# window is a single frame, which is I2V wearing a video's clothes.
MIN_LATENT_INDEX = 1


class ClipError(ValueError):
    """A conditioning clip we refuse to forward. Surfaced to the client as 400."""


def condition_window(condition_seconds: float, fps: int = FPS) -> tuple[tuple[int, ...], int]:
    """Map a requested conditioning duration to latent indexes + pixel frames.

    Conditioning is addressed in *latent* frames and the VAE folds 4 pixel
    frames into 1, so the window quantises upward:

        2.0 s -> 48 frames requested -> indexes 0..12 -> 49 frames actually used

    Returns (indexes, pixel_frames). Callers must report `pixel_frames` back to
    the client rather than echoing the request — the quantised value is what the
    engine will really consume, and the difference is what makes an exactly-2.000s
    clip come up one frame short.
    """
    requested = round(condition_seconds * fps)
    # ceil((requested - 1) / 4) without importing math, floor-division style.
    max_index = max(MIN_LATENT_INDEX, -(-(requested - 1) // VAE_TEMPORAL_COMPRESSION))
    return tuple(range(max_index + 1)), max_index * VAE_TEMPORAL_COMPRESSION + 1


def _encode_jpeg(frame) -> bytes:
    """One decoded frame -> JPEG bytes. An mjpeg container holding a single
    frame *is* a JPEG file, which avoids a Pillow dependency."""
    out = io.BytesIO()
    with av.open(out, mode="w", format="mjpeg") as oc:
        stream = oc.add_stream("mjpeg", rate=1)
        stream.width, stream.height, stream.pix_fmt = frame.width, frame.height, "yuvj420p"
        for packet in stream.encode(frame.reformat(format="yuvj420p")):
            oc.mux(packet)
        for packet in stream.encode():
            oc.mux(packet)
    return out.getvalue()


def sample_frames(video_bytes: bytes, count: int) -> list[bytes]:
    """Evenly-spaced JPEG stills across a clip, for showing a reasoner the motion.

    Opus cannot consume video, so the V2V upsampler is given stills instead
    (STORY_019). They must be drawn from the *same* window the engine conditions
    on — call this on the already-trimmed clip, never the original upload, or the
    prompt will describe motion the model was never shown.

    The last frame is always included: the continuation starts from there, and
    it is the single most important frame for describing "final visible
    configuration" per NVIDIA's V2V contract.
    """
    if count < 1:
        raise ClipError(f"frame sample count must be positive, got {count}")
    try:
        with av.open(io.BytesIO(video_bytes)) as container:
            frames = list(container.decode(video=0))
    except Exception as exc:
        raise ClipError(f"could not decode the clip for frame sampling: {exc}") from exc
    if not frames:
        raise ClipError("clip decoded to zero frames")

    if count >= len(frames):
        picked = frames
    else:
        step = (len(frames) - 1) / (count - 1) if count > 1 else 0
        picked = [frames[round(i * step)] for i in range(count)]
    return [_encode_jpeg(f) for f in picked]


def _stream_fps(stream) -> Fraction:
    rate = stream.average_rate or stream.guessed_rate
    if rate is None:
        raise ClipError("could not determine the source clip's frame rate")
    return rate


def prepare_tail(video_bytes: bytes, want_frames: int) -> tuple[bytes, int, float]:
    """Trim a clip to its final `want_frames` frames.

    Returns (clip_bytes, total_source_frames, fps). A clip that is already
    exactly `want_frames` long is returned byte-identical — no needless
    re-encode, and no generation loss on a signal the model conditions on.
    """
    tail: deque = deque(maxlen=want_frames)
    total = 0
    try:
        with av.open(io.BytesIO(video_bytes)) as container:
            if not container.streams.video:
                raise ClipError("the uploaded file contains no video stream")
            fps = _stream_fps(container.streams.video[0])
            for frame in container.decode(video=0):
                total += 1
                tail.append(frame)
    except ClipError:
        raise
    except Exception as exc:
        raise ClipError(f"could not decode the uploaded video: {exc}") from exc

    if fps != FPS:
        raise ClipError(
            f"source clip must be {FPS} fps, got {float(fps):.3f} fps. The engine "
            f"decodes by frame count with no frame-rate awareness, so another rate "
            f"would be replayed as slow or fast motion; re-encode with "
            f"`ffmpeg -r {FPS}` first"
        )
    if total < want_frames:
        raise ClipError(
            f"source clip has {total} frames but the conditioning window needs "
            f"{want_frames}. A shorter clip is padded by repeating its final frame, "
            f"which tells the model the scene has stopped moving — so this is "
            f"rejected rather than rendered. Supply a longer clip or lower "
            f"condition_seconds"
        )
    if total == want_frames:
        return video_bytes, total, float(fps)

    frames = list(tail)
    out = io.BytesIO()
    try:
        with av.open(out, mode="w", format="mp4") as oc:
            stream = oc.add_stream("libx264", rate=Fraction(FPS, 1))
            stream.width = frames[0].width
            stream.height = frames[0].height
            stream.pix_fmt = "yuv420p"
            for i, frame in enumerate(frames):
                frame = frame.reformat(format="yuv420p")
                # Re-base timestamps: the decoded frames carry the source's pts,
                # which would leave the trimmed clip starting mid-timeline.
                frame.pts = i
                frame.time_base = Fraction(1, FPS)
                for packet in stream.encode(frame):
                    oc.mux(packet)
            for packet in stream.encode():
                oc.mux(packet)
    except Exception as exc:
        raise ClipError(f"could not re-encode the trimmed clip: {exc}") from exc

    return out.getvalue(), total, float(fps)
