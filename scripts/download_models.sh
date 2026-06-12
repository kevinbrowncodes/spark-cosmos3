#!/usr/bin/env bash
# Download the nvidia/Cosmos3-Nano weights (~33 GB) into the Hugging Face
# cache, at the exact path docker-compose.yml serves from:
#
#   $HF_CACHE_DIR/hub/models--nvidia--Cosmos3-Nano/snapshots/main/
#
# NOTE the non-standard layout: a normal `hf download` puts the snapshot under
# a commit-hash directory, but this deployment serves from a literal
# `snapshots/main` directory of plain files. We reproduce that with
# --local-dir, which writes real files (no symlinks into blobs/).
#
# Prereqs:
#   - `pip install -U huggingface_hub` (provides the `hf` CLI)
#   - HF_TOKEN env var, or `hf auth login` already done
#   - License accepted for nvidia/Cosmos3-Nano on huggingface.co
set -euo pipefail

HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"
TARGET="$HF_CACHE_DIR/hub/models--nvidia--Cosmos3-Nano/snapshots/main"

if [ -f "$TARGET/model_index.json" ]; then
    echo "Weights already present at $TARGET — nothing to do."
    exit 0
fi

echo "Downloading nvidia/Cosmos3-Nano (~33 GB) to $TARGET ..."
mkdir -p "$TARGET"

hf download nvidia/Cosmos3-Nano \
    --revision main \
    --local-dir "$TARGET"

echo
echo "Done. Verify with:"
echo "  ls $TARGET"
echo "Then start the service:  docker compose up -d"
