"""Shared video fixtures for the V2V tests (STORY_018).

Since STORY_018 the gateway really decodes conditioning clips, so tests must
supply real ones. Frames are made identifiable by brightness: frame i is filled
with luma i*3, so a decoded frame's mean luma says which source frame it was —
that is how the tail-trim tests prove the *last* N frames were kept.
"""

import io
from fractions import Fraction

import av


def make_clip(n_frames: int, fps: int = 24, w: int = 64, h: int = 48) -> bytes:
    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as oc:
        stream = oc.add_stream("libx264", rate=Fraction(fps, 1))
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        for i in range(n_frames):
            frame = av.VideoFrame(w, h, "yuv420p")
            frame.planes[0].update(bytes([min(255, i * 3)]) * (w * h))
            for plane in frame.planes[1:]:
                plane.update(bytes([128]) * (w * h // 4))
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in stream.encode(frame):
                oc.mux(packet)
        for packet in stream.encode():
            oc.mux(packet)
    return out.getvalue()


def frame_count(clip: bytes) -> int:
    with av.open(io.BytesIO(clip)) as c:
        return sum(1 for _ in c.decode(video=0))


def first_frame_luma(clip: bytes) -> int:
    with av.open(io.BytesIO(clip)) as c:
        for frame in c.decode(video=0):
            plane = bytes(frame.planes[0])
            return round(sum(plane) / len(plane))
    raise AssertionError("clip decoded to zero frames")
