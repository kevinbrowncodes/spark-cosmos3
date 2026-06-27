# STORY 004 — Vendor NVIDIA's Resolution Ratio Dictionary into the Repo

As a gateway operator, I want the canonical resolution/aspect-ratio lookup table stored as a versioned data file, so that size parsing and output param pinning are byte-faithful to NVIDIA's reference and drift is detectable.

## Acceptance Criteria

- [x] `data/resolution_ratio_dict.json` created with values copied verbatim from `RESOLUTION_RATIO_DICT` (lines 59–88) of `cosmos_framework/inference/prompt_upsampling.py` (upstream `github.com/nvidia/cosmos-framework`, branch `main`).
- [x] `data/SOURCES.md` updated with upstream path, sha256 of source file, and pull date.
- [x] Canonical deployment size `720x1280` vertical maps correctly: tier `"720"`, aspect `"9,16"` → `{"W": 720, "H": 1280}`.
- [x] `scripts/sync_config.sh` picks up the new file automatically (no script changes needed — all flat files in `data/` are included).

## Technical Notes

- Source: `https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompt_upsampling.py`, lines 59–88.
- The dict is a plain nested structure: `tier → aspect_ratio → {W, H}`. Extract it and serialise as JSON.
- `(W, H)` pairs are unique across all tiers, so reverse-lookup (used in Story 7's `_parse_size`) is unambiguous.
- This is a data file only — no gateway code changes in this story.

## Testing Plan

- **Unit:** none required — data file only, no code changes.
- **Contract:** none required — no gateway endpoints change.
- **Smoke:** none required — no generation path changes.
- Manual verification: spot-check `720x1280` vertical entry; compare full dict against upstream source.

## Estimated Complexity

XS — data extraction and JSON serialisation only.
