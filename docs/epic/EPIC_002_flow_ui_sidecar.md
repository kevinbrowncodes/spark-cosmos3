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
| Default size / frames | **720x1280**, frames **`[121, 189, 237]`**, default 189, steps `[35, 50]` default 35 | Matches production. The example's `300` is rejected by our gateway: 300/24 = 12 s, outside the upsampler schema's 2 s–10 s cap → HTTP 400. 237 (9.9 s) is the real I2V ceiling. |
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
| `frames` options `[121, 189, 237, 300]` | 300 → 400 (12 s > 10 s cap) | drop 300 |
| `duration_s = job["seconds"]` | `docs/api.md` §"seconds": the status payload's `"seconds": "4"` is an **unused default**, not the clip length | `duration_s = frames / 24` from the values we submitted (generated frames on extend) |
| `count` options `[1, 2]` | serial queue, uncancellable | `[1]` |
| always posts the reference as `image=` | a video reference must go as `video=` with `condition_seconds` | branch on the asset's kind (STORY_026) |
| no `seed` | correct as-is: the protocol fills a default for **every** declared field, so a `seed` field would pin every render to one seed. Leave it out; the gateway randomises. | none |

### Protocol facts that shape the design

- **One mode only.** `ModeKey` is `Literal["image", "video"]` and names the
  *output* type, so Generate and Extend share the single `video` mode and one
  `frames` control. The sidecar validates per reference kind:
  image reference → `frames ≤ 263` (int(frames/24) ≤ 10);
  video reference → `frames` must be 4k+1 and `frames − 73 ≤ 240`.
  Violations return **422 with a plain-English `detail`** — the UI shows it verbatim.
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
Generate (image reference)
  frames ∈ {121, 189, 237}          duration = frames / 24 ≤ 10 s

Extend (video reference, condition_seconds = 3.0)
  conditioning  73 frames (3.04 s)  ← last 3 s of the chosen clip
  frames = 313  → 240 generated     = 10.0 s of new video   ← the target
  frames = 237  → 164 generated     =  6.8 s
  frames = 189  → 116 generated     =  4.8 s
  frames = 121  →  48 generated     =  2.0 s
```

All four are 4k+1. `313` is offered in the list and rejected with a clear
422 when the reference is an image. Extending our own outputs always works —
they are 24 fps and ≥ 5 s. A foreign upload must be 24 fps and ≥ 3 s or the
gateway returns 400 (EPIC_001 limitations #1–#2), surfaced verbatim.

### Time and money

| Action | Size | Frames | Approx. |
|---|---|---|---|
| Generate | 704x1280 | 189 | ~44 min |
| Extend | 704x1280 | 313 | ~80 min |
| Extend (smoke) | 832x480 | 313 | ~26 min |

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

---

## Stories

| # | Story | Delivers |
|---|---|---|
| **023** | The Flow UI runs beside the gateway in its own container | `flow/Dockerfile`, `flow/gateway.py` (verbatim copy), compose service on 8003, `FLOW_MEDIA_DIR` + `FLOW_VERSION` in `.env.example`, deploy.sh builds it, `flow-conformance http://localhost:8003` (contract-only) passes. Stale `AEON_URL` removed from `.env.example`. |
| **024** | The Flow UI only offers settings Cosmos will accept | The `docs/api.md` corrections above: frames list, `count [1]`, `duration_s` from frames, per-kind frame validation with plain-English 422s. Unit tests for the mapping. |
| **025** | Generate one clip end to end from the Flow UI | Eager output caching on `done`; `flow-conformance --generate --reference <still> --timeout 3600` passes; one clip generated through `http://localhost:8003/ui/`; README + `docs/api.md` sections. |
| **026** | Extend a finished clip from the Flow UI | `reference_kinds: ["image", "video"]`; video reference → `video=` + `condition_seconds=3.0`; 313 default-able; one extend rendered at 480p and reviewed for seam continuity. |

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
5. **Extend inherits EPIC_001's limitations** — 24 fps sources only, seam
   colour shift from the VAE round-trip, invented audio under the recycled
   3 s prefix, and the recycled prefix is *not* trimmed from the extended clip
   (the pipeline does that splice; the UI shows the raw output).
6. **Projects and batches live in the browser.** Clearing site data for
   `localhost:8003` loses the layout, not the media.

## Definition of Done

- [ ] `docker compose up -d flow` serves `http://localhost:8003/ui/` and the UI boots against `/flow/capabilities` without a protocol-mismatch screen
- [ ] `flow-conformance http://localhost:8003` passes (contract)
- [ ] `flow-conformance http://localhost:8003 --generate --reference <still> --timeout 3600` passes (one real render)
- [ ] One clip generated from a still through the UI, playable in the tile
- [ ] One clip **extended** through the UI from a finished output, conditioned on its last 3 s
- [ ] Every option the UI offers is accepted by `:8002/generate`, or rejected by the sidecar with a plain-English 422 before reaching it
- [ ] `gateway/server.py` unchanged across the whole epic (`git log -- gateway/server.py` shows no commits from STORY_023–026)
- [ ] `FLOW_VERSION` documented in `.env.example` and README; upgrade procedure written down
- [ ] `./scripts/deploy.sh` builds and labels the `flow` image
