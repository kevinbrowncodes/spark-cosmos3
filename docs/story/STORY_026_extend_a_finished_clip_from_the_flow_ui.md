# STORY_026 — Extend a finished clip from the Flow UI

**Epic:** EPIC_002 — A browser UI for generating and extending clips
**Depends on:** STORY_025 (finished clips are cached on disk), EPIC_001 (the gateway's V2V path)
**Unblocks:** EPIC_002 Definition of Done

As someone using the Flow UI, I want to pick a clip I already made as the
reference and get the next N seconds of it, so that a scene can be carried
forward the way the pipeline chains clips — motion history and all — without
leaving the browser.

## Acceptance Criteria

- [x] `capabilities.reference_kinds` is `["image", "video"]`; the asset picker's *Videos* tab lists finished outputs and uploaded clips
- [x] A video reference is sent to the gateway as the `video=` multipart part with `condition_seconds=3.0`; an image reference still goes as `image=` — the asset's kind decides, nothing else
- [x] With a video reference, `frames = snap4k1(73 + L·24)` (193 / 265 / 313) and the gateway accepts every Length: proven by the existing validator cross-check test, now covering the video branch on the wire
- [x] After the finished extend is cached, the sidecar **trims the recycled prefix**: `flow-outputs/<id>.mp4` holds exactly frames `[condition_frames:]` (frame-accurate, video and audio), and the untouched original is moved to `flow-outputs-raw/<id>.mp4`, which the media store does not list
- [x] `condition_frames` is read from the gateway's `/generate` response (never assumed); a Generate job (`condition_frames: null`) is cached unchanged
- [x] The extended tile reports `duration_s` = the Length asked for, and the served file's real duration matches it to within one frame
- [x] If ffmpeg fails, the raw file is served unchanged and the failure is logged — never a lost clip
- [x] E2E: one extend rendered on the box at 832x480, Length 10, from a cached Generate output, then reviewed: the served clip is 10.0 s, starts where the source ended, and the seam is continuous (colour shift acceptable, replay is not) — `run_e3bd921556a7` clip 2, served 10.000 s / 240 frames from a 313-frame raw; the seam measured at 27.94 dB against the source's last frame versus 18.34 dB against the frame 73 back, so it continues rather than replays (`docs/evidence/STORY_026/seam-analysis.txt`)
- [x] `flow-conformance http://localhost:8003` still passes; `contract.sh` asserts `reference_kinds`
- [x] `flow/` stays ≥ 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

**Extend is a picker choice, not a mode.** `ModeKey` names the *output* type,
so Extend shares the `video` mode; the reference's kind (`flow_protocol.media.kind_of`)
chooses the wire shape. The upstream example always sent `image=`; here:

```python
part = "video" if kind == "video" else "image"
form["frames"] = str(frames_for(length, kind))
if kind == "video":
    form["condition_seconds"] = str(CONDITION_SECONDS)      # 3.0 → 73 frames (EPIC_001)
```

**What comes back.** The gateway's `/generate` response carries
`condition_frames` (73) and `generated_frames` (L·24) on the V2V path — see
`docs/api.md` and EPIC_001. Remember both per job alongside size and length.
`/jobs/{id}` repeats them while the gateway remembers the job.

**Trim, frame-accurately.** After `_cache_output` lands the raw file:

```
ffmpeg -y -loglevel error -i raw.mp4
       -vf "select='gte(n,73)',setpts=PTS-STARTPTS"
       -af "atrim=start=3.0416667,asetpts=PTS-STARTPTS"
       -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -c:a aac -movflags +faststart out.mp4
```

A re-encode is the only frame-accurate cut (`-ss` with stream copy snaps to
keyframes). ~10–30 s of CPU for a 10 s 720p clip; the poll that reports
`done` returns late once. `atrim` start is `condition_frames / 24` exactly.
Write to `<id>.part.mp4`, then `rename` — the media store lists only complete
files. Trimming happens once: if `flow-outputs-raw/<id>.mp4` already exists,
skip.

**Raw stays, unlisted.** `MediaStore` only knows the `in` and `out` roots, so
`flow-outputs-raw/` never appears in `/flow/media`. It is there for provenance
and for re-trimming if the recipe changes.

**Source clip rules are the gateway's.** Our own outputs are 24 fps and ≥ 5 s,
so they always qualify. A foreign upload that is short or not 24 fps is
refused by the gateway with a 400 the UI shows verbatim (EPIC_001 limitations
#1–#2); the sidecar does not re-implement those checks.

**Duration on the tile.** `duration_s` stays the remembered Length; after the
trim the file *is* that long. `ffprobe` confirms it in the E2E.

**Memory gate.** The E2E render runs only when `free -h` shows headroom and
no NVRM OOM lines appear in the kernel log for the day (see BUG_004's sibling
note in EPIC_002 status). 480p extend ≈ 26 min.

## Testing Plan

- **Unit**: `trim_prefix(raw, out, condition_frames)` builds the exact ffmpeg argv (select index, atrim seconds), returns the trimmed path, and on a non-zero exit returns `None` leaving `raw` in place; `_finalise_output` chooses trim vs no-op from remembered `condition_frames`; `frames_for(…, "video")` values.
- **Integration**: `POST /flow/generate` with a video-kind reference sends `name="video"`, `condition_seconds=3.0`, `frames=265` (Length 8); an image reference still sends `name="image"` and no `condition_seconds`; a `done` poll for an extend job caches, trims (ffmpeg on a 64×64 synthetic clip with a tone track), moves the raw aside, and `GET /flow/media/out:<id>.mp4` serves a file whose frame count is `total − 73` (checked with ffprobe); a Generate job is not trimmed; ffmpeg failure path serves the raw file; in-process conformance still green.
- **Contract**: `contract.sh` asserts `reference_kinds == ["image","video"]`.
- **E2E**: the 480p extend on the box, reviewed as above; screenshot of the picker's Videos tab and of the extended tile under `docs/evidence/STORY_026/`.
- **Coverage**: `--cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Medium.** ~80 lines (wire branch, remembered meta, trim helper) and a test
fixture that needs ffmpeg + ffprobe; the render is 26 minutes when the box
allows it.
