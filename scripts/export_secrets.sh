#!/usr/bin/env bash
# Read HF_TOKEN and ANTHROPIC_API_KEY from this machine and print them in
# KEY=value format, one per line. Called remotely by import_secrets.sh on
# Spark 2 — do not run directly unless you want the values printed to stdout.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

HF_TOKEN=$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)
ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' "$REPO_DIR/.env" 2>/dev/null | cut -d= -f2- || true)

if [ -z "$HF_TOKEN" ]; then
    echo "ERROR: HF_TOKEN not found at ~/.cache/huggingface/token" >&2
    exit 1
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not found in $REPO_DIR/.env" >&2
    exit 1
fi

printf 'HF_TOKEN=%s\nANTHROPIC_API_KEY=%s\n' "$HF_TOKEN" "$ANTHROPIC_API_KEY"
