# EPIC_002 — A browser UI for generating and extending clips

**Status:** Planned
**Stories:** STORY_023 → STORY_026
**Related:** EPIC_001 (V2V), BACKLOG_002 (upstream Flow work this epic depends on for cancel/ETA/extend button)
**Upstream:** https://github.com/kevinbrowncodes/flow — `protocol/PROTOCOL.md`, `protocol/python/README.md`, release `v0.1.0`

---

## Goal

Today the only way to render a clip on this box is `curl` or the
`ogtv-studios` pipeline. This epic puts the **Flow UI** in front of the
gateway so a person can attach a still, type a beat, watch the bar move, and
play the result in a browser — and then **extend** that result: pick the
finished clip as the source and generate the next 10 seconds from its last
3 seconds, the same chaining the pipeline does.

The UI arrives as a **sidecar container** (`flow`, port **8003**). It speaks
the Flow Gateway Protocol v1 to the browser and only ever calls the existing
gateway routes on `:8002`. **`gateway/server.py` is not edited by any story in
this epic.**

## Scope

**In scope**

- A `flow` compose service: `python:3.12-slim` + ffmpeg, `flow-protocol[server]`
  pinned to a flow git tag, the matching `flow-ui-<tag>.tar.gz` unpacked to
  `/app/flow-ui`, served by uvicorn on `:8003`.
- `flow/gateway.py` — a copy of the upstream `examples/cosmos3.py`, corrected
  wherever it disagrees with `docs/api.md`.
- Image-to-video from an uploaded still (**Generate**).
- Video-to-video from a finished clip (**Extend**).
- Conformance: `flow-conformance` contract checks on every change, plus one
  real render before any pin bump.
- `FLOW_VERSION` in `.env.example` and the README; the upgrade path is *bump
  the pin → rebuild the image → re-run conformance*.

**Out of scope**

- Any change to `gateway/server.py`, the engine, or the progress sidecar.
- Cancelling a running render from the UI, a per-tile ETA, and a dedicated
  "Extend" button on a tile. Protocol v1 has none of these and UI v0.1.0
  renders none of them; they are flow-repo work, tracked in **BACKLOG_002**.
- More than one output per submit (see *Decisions*).
- Auth, multi-user, quotas, cost. The box is single-user on a private LAN.
- Projects/batches persistence server-side — Flow keeps those in the browser.

---

## Decisions (agreed 2026-09-06)

| Question | Decision | Why |
|---|---|---|
| Default size / length | **720x1280**; a **Length** control in *seconds of new video* — `[5, 8, 10]`, default 8, role `duration`; steps `[35, 50]` default 35 | One control that means the same thing for Generate and Extend; the sidecar does the frame maths per reference kind. Replaces the example's raw `frames` list, whose `300` our gateway rejects (300/24 = 12 s, outside the upsampler schema's 2 s–10 s cap → HTTP 400). |
| Extend output | **Trimmed to the new footage.** The sidecar drops the first 73 frames (the VAE re-render of the source's last 3 s) with ffmpeg after download; the raw 313-frame file is kept in `flow-outputs-raw/`, which the media store does not list. | "Length: 10 s" then yields a 10.0 s file labelled 10.0 s. Chained extends concatenate with nothing to discard — the splice the pipeline does by hand (`clip[condition_frames:]`). Removes the invented-audio-under-recycled-video artefact too. |
| Tests | Every story ships **unit + integration + e2e** tests; `flow/` holds **≥ 95 % line coverage** from STORY_023 on. Lifting `gateway/` (77 % on 2026-09-06, `server.py` 61 %) is a **separate follow-on story**, not part of this epic. | CLAUDE.md §3.5 / §4.2 as amended 2026-09-06. Nothing here edits `server.py`, so the two efforts do not collide. |
| Outputs per submit | **`count` locked to `[1]`** | The UI's X only deletes the tile from localStorage — the render keeps running. Real cancellation is `DELETE :8002/jobs/{id}?hard=true`, which restarts the engine and wipes every other queued job. Until Flow ships cancel + ETA, nothing may be queued that cannot be stopped cleanly. |
| V2V | **In this epic**, as "Extend" | The picker already grows a *Videos* tab of finished outputs when `reference_kinds` includes `video` (`AssetPickerModal.jsx:20`). Picking a clip and generating *is* extend. |
| Conditioning window | **3 s** (`condition_seconds=3.0` → 73 frames, 3.04 s) | EPIC_001's blind A/B (2026-07-28) adopted 3 s over 2 s; the pipeline passes it explicitly. The gateway default (0.2 s, `server.py:65`) is the engine minimum, not a recommendation. |
| Media directory | **`~/Documents/flow-media`**, `FLOW_MEDIA_DIR` in `.env` | Keeps UI scratch out of `cosmos-media`, which CLAUDE.md defines as a deploy artifact. |
| Port | **8003** | Free on this box (AEON's old port; that `.env.example` entry is stale and is removed in STORY_023). |

---

## Shared technical constraints

Verified against flow `v0.1.0` and this repo's gateway on 2026-09-06.

### What the sidecar may call

Exactly three gateway routes, all pre-existing:

| Sidecar need | Gateway route |
|---|---|
| submit | `POST :8002/generate` (multipart; `image=` **or** `video=`) |
| poll | `GET :8002/jobs/{id}` |
| bytes | `GET :8002/jobs/{id}/content` |

No new gateway route, field, or behaviour. If the copied `cosmos3.py` and
`docs/api.md` disagree, **`docs/api.md` wins** — fix the copy, note it in the
story.

### Where the upstream example is wrong for this box

Found by reading `examples/cosmos3.py` against `docs/api.md` and `server.py`:

| Example does | Reality | Fix (STORY_024) |
|---|---|---|
| `frames` options `[121, 189, 237, 300]` | 300 → 400 (12 s > 10 s cap); and a raw frame count means different things on Generate vs Extend | replace with **Length** in seconds of new video; sidecar computes `frames` |
| `duration_s = job["seconds"]` | `docs/api.md` §"seconds": the status payload's `"seconds": "4"` is an **unused default**, not the clip length | `duration_s = Length` — the new footage, which after trimming *is* the file length |
| `count` options `[1, 2]` | serial queue, uncancellable | `[1]` |
| always posts the reference as `image=` | a video reference must go as `video=` with `condition_seconds` | branch on the asset's kind (STORY_026) |
| no `seed` | correct as-is: the protocol fills a default for **every** declared field, so a `seed` field would pin every render to one seed. Leave it out; the gateway randomises. | none |

### Protocol facts that shape the design

- **One mode only.** `ModeKey` is `Literal["image", "video"]` and names the
  *output* type, so Generate and Extend share the single `video` mode and one
  **Length** control. The sidecar turns Length into `frames` per reference
  kind (table below) and never offers a value `:8002` would reject. Anything
  the gateway still refuses (a foreign clip that is too short or not 24 fps)
  comes back as its 400 `detail`, which the UI shows verbatim.
- **`reference: "required"`.** There is no T2V path; the engine dispatches on
  the media it receives (EPIC_001).
- **`progress: "percent"`** is honest: the gateway's elapsed-time estimate
  moves during `in_progress`, which is what conformance checks for
  (`0 < progress < 100` seen at least once).
- **Thumbnails must be `image/*`.** The reference router extracts a poster
  frame with ffmpeg — hence ffmpeg in the image.
- **Media ids** are `<root>:<filename>`; the store roots are
  `/media/flow-uploads` (`in:`) and `/media/flow-outputs` (`out:`).
- **The UI bundle is a flat tarball** (`tar -czf … -C dist .`), so it unpacks
  straight into `/app/flow-ui` with no `--strip-components`. Confirmed on the
  v0.1.0 asset (26 entries, `./index.html` at root).
- **Pin the same tag twice** — `flow-protocol` (pip) and `flow-ui` (tarball)
  are released together; `FLOW_VERSION` feeds both in the Dockerfile.

### Frame arithmetic (from EPIC_001)

```
Length L (seconds of new video) ∈ {5, 8, 10}, fps 24

Generate (image reference)
  frames = L·24                     5→120   8→192   10→240
  gateway duration label = int(frames/24) = L      (all inside '2s'–'10s')

Extend (video reference, condition_seconds = 3.0 → 73 conditioning frames)
  frames = snap4k1(73 + L·24)       5→193   8→265   10→313
  generated = frames − 73           5→120   8→192   10→240
  trimmed file = generated / 24 = L seconds
```

`snap4k1` rounds *up* to the next 4k+1 (the VAE folds 4 pixel frames into 1
latent; `_prepare_latents_v2v` hard-fails otherwise). 73 + L·24 already lands
on 4k+1 for all three values, so no snapping happens today; the helper exists
so a future Length option cannot break the rule. Extending our own outputs
always works — they are 24 fps and ≥ 5 s. A foreign upload must be 24 fps and
≥ 3 s or the gateway returns 400 (EPIC_001 limitations #1–#2), surfaced verbatim.

### Trim the recycled prefix on Extend

The raw Extend output is `73 + generated` frames: the first 3.04 s are a VAE
round-trip of the source's tail, not new footage. After the download the
sidecar writes `flow-outputs/<job>.mp4` = frames `[73:]` via ffmpeg
(frame-accurate: re-encode, `select='gte(n,73)'` + matching `atrim`), and
moves the untouched original to `flow-outputs-raw/<job>.mp4`. `condition_frames`
comes from the `/generate` response — never assumed. Generate outputs are
cached unchanged.

### Time and money

| Action | Size | Frames | Approx. |
|---|---|---|---|
| Generate, Length 8 | 704x1280 | 192 | ~44 min |
| Extend, Length 10 | 704x1280 | 313 | ~80 min |
| Extend, Length 10 (smoke) | 832x480 | 313 | ~26 min |

`flow-conformance --generate` defaults to a **900 s** deadline, so on this
box it is always run with `--timeout 3600`.

### Cache outputs on completion, not on first view

vLLM-omni's job records live in engine memory: an engine restart (hard cancel,
reboot, OOM) forgets every job, and `/jobs/{id}/content` then 404s. The
upstream example fetches the mp4 lazily on first `/media` access, which loses
any finished clip nobody has clicked yet. The sidecar must download the clip
into `/media/flow-outputs` **as soon as a poll reports `done`**, so a finished
render survives the engine. (STORY_025.)

### Operational rules that still apply

- Never restart the engine during a render; the `flow` container may be
  rebuilt/restarted freely — it holds no GPU state and only in-memory
  size hints that `/jobs/{id}` re-supplies.
- `./scripts/deploy.sh` must build `flow` too and bake `GIT_SHA` as a label
  (STORY_013 convention).
- Memory: the sidecar is a small Python process; no `free -h` gate needed.

### Testing rules for every story in this epic

- **Unit**: pure functions in `flow/` (Length→frames, status mapping, id
  parsing, trim arithmetic). **Integration**: `TestClient(create_app(...))`
  with the `:8002` gateway faked by `respx`/a stub app — every `/flow` route
  and error path, including the conformance suite run in-process via
  `flow_protocol.conformance.run_checks`. **E2E**: `flow-conformance` against
  the running container, and the real renders named in the story.
- Coverage: `python3 -m pytest --cov=flow --cov-fail-under=95`. STORY_023
  adds `requirements-dev.txt` (pytest, pytest-cov, respx) and a
  `.venv` recipe, since the host Python is PEP 668-locked.
- `pytest.ini` gains `flow/tests`; the `flow` image runs the same tests at
  build time so a broken sidecar never becomes an image.

---

## Stories

| # | Story | Delivers |
|---|---|---|
| **023** | The Flow UI runs beside the gateway in its own container | `flow/Dockerfile`, `flow/gateway.py` (verbatim copy), compose service on 8003, `FLOW_MEDIA_DIR` + `FLOW_VERSION` in `.env.example`, deploy.sh builds it, `flow-conformance http://localhost:8003` (contract-only) passes. Stale `AEON_URL` removed from `.env.example`. |
| **024** | The Flow UI only offers settings Cosmos will accept | The `docs/api.md` corrections above: the **Length** control and its per-kind frame maths, `count [1]`, `duration_s = Length`. Unit + integration tests for the whole mapping. |
| **025** | Generate one clip end to end from the Flow UI | Eager output caching on `done`; `flow-conformance --generate --reference <still> --timeout 3600` passes; one clip generated through `http://localhost:8003/ui/`; README + `docs/api.md` sections. |
| **026** | Extend a finished clip from the Flow UI | `reference_kinds: ["image", "video"]`; video reference → `video=` + `condition_seconds=3.0`; the 73-frame prefix trimmed after download, raw kept unlisted; one extend rendered at 480p and reviewed for seam continuity. |

**Follow-on, outside this epic:** a story lifting `gateway/` test coverage
from 77 % to 95 % (mostly `server.py` handlers via faked-engine integration
tests) so `--cov=gateway` can join the pre-commit gate.

Stories ship **in order, one at a time** (CLAUDE.md §10.5). 023 is deliberately
a thin slice — the container boots and answers the contract before any
Cosmos-specific correction is made.

## Known limitations (documented, not fixed by this epic)

1. **The X on a tile does not stop the render.** It deletes the browser
   record only. The GPU finishes the job; the clip still lands in
   `/media/flow-outputs`. Stated in `capabilities.strings.footer`.
2. **No ETA in the UI.** The gateway reports `eta_s` and the sidecar passes it
   through (unknown keys are allowed), but UI v0.1.0 does not render it. The
   footer carries the static per-render estimate instead.
3. **No "Extend" button.** Extend is *pick a clip in the Videos tab*. A
   one-click affordance is BACKLOG_002.
4. **Outputs are never pruned.** ~10–50 MB per clip in `~/Documents/flow-media`.
   Prune by hand.
5. **Extend inherits EPIC_001's source-side limitations** — 24 fps sources
   only, and a small colour/detail shift at the seam because the model
   continues from a VAE re-render of the tail rather than the original pixels.
   (The recycled prefix and its invented audio are trimmed away — see *Trim
   the recycled prefix*.)
6. **Projects and batches live in the browser.** Clearing site data for
   `localhost:8003` loses the layout, not the media.

## Definition of Done

- [ ] `docker compose up -d flow` serves `http://localhost:8003/ui/` and the UI boots against `/flow/capabilities` without a protocol-mismatch screen
- [ ] `flow-conformance http://localhost:8003` passes (contract)
- [ ] `flow-conformance http://localhost:8003 --generate --reference <still> --timeout 3600` passes (one real render)
- [ ] One clip generated from a still through the UI, playable in the tile
- [ ] One clip **extended** through the UI from a finished output, conditioned on its last 3 s; the served file is exactly the new footage (Length seconds), raw kept unlisted
- [ ] Every story shipped unit + integration + e2e tests; `flow/` holds ≥ 95 % line coverage
- [ ] Every option the UI offers is accepted by `:8002/generate`, or rejected by the sidecar with a plain-English 422 before reaching it
- [ ] `gateway/server.py` unchanged across the whole epic (`git log -- gateway/server.py` shows no commits from STORY_023–026)
- [ ] `FLOW_VERSION` documented in `.env.example` and README; upgrade procedure written down
- [ ] `./scripts/deploy.sh` builds and labels the `flow` image
