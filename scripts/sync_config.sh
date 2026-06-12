#!/usr/bin/env bash
# Deploy this repo's canonical config to the runtime location.
#
# Everything in data/ (version-controlled, canonical) is consumed by the
# pipeline at runtime from the cosmos-media directory (mounted into its
# container as /cosmos-media). This script pushes the repo copies there.
#
#   ./scripts/sync_config.sh           # deploy (shows diff first if any)
#   ./scripts/sync_config.sh --check   # drift check only, exit 1 on drift
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_DIR/data"
DEST_DIR="${COSMOS_MEDIA_DIR:-$HOME/Documents/cosmos-media}"

drift=0
for src in "$SRC_DIR"/*; do
    [ -f "$src" ] || continue
    name="$(basename "$src")"
    dest="$DEST_DIR/$name"
    if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
        echo "in sync: $name"
        continue
    fi
    drift=1
    if [ -f "$dest" ]; then
        echo "drift detected — live $name differs from repo:"
        diff -u "$dest" "$src" || true
    else
        echo "live copy missing: $dest"
    fi
    if [ "${1:-}" != "--check" ]; then
        cp "$src" "$dest"
        echo "deployed: data/$name -> $dest"
    fi
done

if [ "${1:-}" = "--check" ] && [ "$drift" -ne 0 ]; then
    exit 1
fi
