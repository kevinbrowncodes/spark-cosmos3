# Vendored data file provenance

All files here are pulled verbatim from upstream. Do not hand-edit.
To check for upstream drift: `./scripts/check_upsampler_sources.sh`

---

## upsampler_template.txt

| Field | Value |
|---|---|
| Upstream repo | `github.com/nvidia/cosmos-framework` (branch `main`) |
| Upstream path | `cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_prompt.txt` |
| Raw URL | `https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_prompt.txt` |
| sha256 | `bc96ddc77589ad6bd67868bbbc01e9cc881bb13e9b267c77f93aa79d15e32948` |
| Pulled | 2026-06-27 |

**Placeholder audit:** grep for `$` tokens confirms exactly five known placeholders and nothing else:
`$image_note`, `$intro`, `$json_template`, `$nl_description`, `$resolution_ratio_dict`.
No brace-style fallback needed — substitution values are never re-scanned by `string.Template`.

---

## upsampler_schema.json

| Field | Value |
|---|---|
| Upstream repo | `github.com/nvidia/cosmos-framework` (branch `main`) |
| Upstream path | `cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_json_schema.json` |
| Raw URL | `https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_json_schema.json` |
| sha256 | `71dec36058538e5b99649fcc81d2c19fd48cb0a701e0510af1f443552052c797` |
| Pulled | 2026-06-27 |

Fills the `$json_template` placeholder in `upsampler_template.txt`. Must be vendored alongside the
template — they travel together.

---

## resolution_ratio_dict.json

| Field | Value |
|---|---|
| Upstream repo | `github.com/nvidia/cosmos-framework` (branch `main`) |
| Upstream path | `cosmos_framework/inference/prompt_upsampling.py` (variable `RESOLUTION_RATIO_DICT`, lines 59–88) |
| Raw URL | `https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompt_upsampling.py` |
| sha256 (source file) | `9e120a0436403ae3f82f22b5158d4409987e9453c2eb69654ca382e179c74942` |
| Pulled | 2026-06-27 |

Extracted from the Python source via `ast.literal_eval` and serialised as JSON. The canonical
deployment size `720x1280` vertical maps to tier `"720"`, aspect `"9,16"` → `{"W": 720, "H": 1280}`.
`(W, H)` pairs are unique across all tiers, so reverse-lookup is unambiguous.
