# STORY 003 — Copy NVIDIA's Official Upsampler Template and Schema into the Repo

As a gateway operator, I want the upsampler to build prompts from NVIDIA's vendored template and schema files, so that future re-vendors are explicit and checkable rather than relying on hand-written strings.

## Acceptance Criteria

- [ ] `data/upsampler_template.txt` copied byte-for-byte from `cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_prompt.txt` (upstream `github.com/nvidia/cosmos-framework`, branch `main`).
- [ ] `data/upsampler_schema.json` copied byte-for-byte from `cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_json_schema.json` (same upstream).
- [ ] `data/SOURCES.md` created with: upstream raw URL, sha256, and pull date for each file.
- [ ] Template file grepped for `$` tokens; only the five known placeholders (`$intro`, `$image_note`, `$nl_description`, `$json_template`, `$resolution_ratio_dict`) are present. Result recorded in `data/SOURCES.md`.
- [ ] `scripts/sync_config.sh` confirmed to include the new files so they reach the runtime location alongside `neg.json` and `audio.txt`.

## Technical Notes

- Fetch source: raw GitHub URLs under `https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompting_templates/external_api/`.
- `string.Template` is safe: substitution values (including the schema) are never re-scanned, so `$` characters in the schema cannot trigger a `ValueError`. The template itself has been verified to contain only the five known placeholders.
- The regression guard (grep for `$` in the template) is for future re-vendors, not a current issue.
- Both files must be synced to `~/Documents/cosmos-media/` via `sync_config.sh` before the gateway will pick them up at runtime.

## Testing Plan

- **Unit:** none required — this story is data files only, no code changes.
- **Contract:** none required — no gateway endpoints change.
- **Smoke:** none required — no generation path changes.
- Manual verification: sha256 of vendored files matches the fetched raw content; `sync_config.sh --check` shows no drift after sync.

## Estimated Complexity

XS — file copy + provenance recording only.
