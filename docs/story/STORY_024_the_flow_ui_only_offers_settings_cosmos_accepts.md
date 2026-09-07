# STORY_024 — The Flow UI only offers settings Cosmos will accept

**Epic:** EPIC_002 — A browser UI for generating and extending clips
**Depends on:** STORY_023 (the sidecar exists)
**Unblocks:** STORY_025 (first real render), STORY_026 (Extend)

As someone using the Flow UI, I want every option in the composer to be one
this box will actually run, so that a click never comes back as a gateway
400 and the numbers on the tile mean what they say.

## Acceptance Criteria

- [x] The `frames` control is gone; a **Length** control (`key: length`, `role: duration`) offers **5 s / 8 s / 10 s** of *new video*, default **8 s**
- [x] The sidecar computes `frames` from Length per reference kind: image → `snap4k1(L·24)` = 121 / 193 / 241; video → `snap4k1(73 + L·24)` = 193 / 265 / 313 (the video branch is exercised by unit tests here and wired to the wire in STORY_026)
- [x] Every Generate value the UI can produce is accepted by `POST :8002/generate` — asserted by a unit test that runs each (size, length, steps) through the gateway's own `upsampler._parse_size` and frame-ceiling rules
- [x] `count` offers only **1** (`options: [1]`, default 1)
- [x] `Job.duration_s` is the Length the job was submitted with (remembered per job), falling back to the gateway's `generated_frames / 24` when present — **never** the status payload's `seconds`, which `docs/api.md` documents as an unused default
- [x] A reference that is not an image is refused with a plain-English 422 (Extend lands in STORY_026)
- [x] `capabilities.strings.footer` states that the box renders one clip at a time with the approximate wall-clock cost, and that removing a tile does not stop a render (EPIC_002 known limitations 1–2)
- [x] The header of `flow/gateway.py` lists every deviation from the upstream example so a future `FLOW_VERSION` bump can re-diff it
- [x] `flow-conformance http://localhost:8003` still passes on the box; `flow/tests/contract.sh` additionally checks the new field shape
- [x] `flow/` stays ≥ 95 % line coverage; `gateway/server.py` untouched

## Technical Notes

**Why Length, not frames.** One `video` mode serves both Generate and Extend
(`ModeKey` is the *output* type), so one control has to mean the same thing in
both. "Seconds of new video" does; a raw frame count does not — 189 frames is
7.9 s of video from a still but only 4.8 s of new footage after a 3 s
conditioning window. The `duration` role also makes the UI render the
"Video length" line for free.

**Frame maths.** The VAE folds 4 pixel frames into 1 latent, so frame counts
are snapped *up* to 4k+1 in both modes. The gateway only enforces this on the
V2V path, but the I2V production default (189) has always been 4k+1 and there
is no reason to hand the model an off-grid count from the UI:

```
L (s)   image  → frames   label   video → frames   generated   label
5       121  (5.04 s)     '5s'    193   (73+120)    120         '5s'
8       193  (8.04 s)     '8s'    265   (73+192)    192         '8s'
10      241  (10.04 s)    '10s'   313   (73+240)    240         '10s'
```

The label column is the gateway's `int(generated/24)` duration check
(`upsampler._parse_size`, `'2s'`–`'10s'`); all six are inside it, all are
under the 720p ceiling of 300 for I2V, and 313 is allowed for V2V because the
duration is measured on generated frames (EPIC_001 / STORY_020). A refinement
on the epic's arithmetic table, which showed unsnapped I2V counts; the story is
the spec.

**Duration.** `generated_frames` is `null` on I2V (`server.py:266`), so the
sidecar remembers the Length per job id alongside the size hint it already
keeps, and reads `generated_frames` only as a fallback (a sidecar restart loses
the hint; a V2V job still reports correctly). After STORY_026 trims the
prefix, the file length *is* the Length in both modes.

**Deviations from upstream `cosmos3.py`** (recorded in the file header):
`frames` → `length` + `frames_for()`; `count` `[1, 2]` → `[1]`; `duration_s`
source; non-image reference refused; footer text; `_sizes_by_job` →
`_meta_by_job`.

## Testing Plan

- **Unit**: `snap4k1` (already-4k+1, +1..+3 cases); `frames_for` for every Length × kind (the table above); the "every UI value is accepted by the gateway" test imports `gateway/upsampler.py`'s `_parse_size` and `server.py`'s frame ceiling and asserts no `ValueError` for all (size ∈ resolution dict, length ∈ {5,8,10}, kind ∈ {image, video}); `_to_job` duration precedence (remembered length > `generated_frames` > None; `seconds` ignored).
- **Integration**: `POST /flow/generate` with length 8 sends `frames=193`; default values send 193; `length: 12` → 422; `count: 2` → 422; video-kind reference → 422 with the plain-English detail; `Job.duration_s` round-trips through `/flow/jobs/{id}`; in-process conformance still green.
- **Contract**: `contract.sh` asserts the capabilities carry `length` with `role: duration` and options `[5, 8, 10]`, `count` options `[1]`, and no `frames` key.
- **E2E**: not applicable — no render; the settings are proven against the gateway's *validators* here and against the engine in STORY_025.
- **Coverage**: `--cov=flow --cov-fail-under=95`.

## Estimated Complexity

**Small.** ~60 lines in `flow/gateway.py`, mostly replacing the field table
and adding two pure helpers; the work is in the tests.
