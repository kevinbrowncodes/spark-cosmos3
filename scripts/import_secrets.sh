#!/usr/bin/env bash
# Pull HF_TOKEN and ANTHROPIC_API_KEY from Spark 1 and write them into .env
# on this machine. Run this on Spark 2 after cloning the repo.
#
# Usage: ./scripts/import_secrets.sh [spark1-host]
# Default host: 192.168.1.33  (override with SPARK1_HOST env var)
set -euo pipefail

SPARK1="${1:-${SPARK1_HOST:-192.168.1.33}}"
SPARK1_USER="${SPARK1_USER:-kevinbrown}"
SPARK1_REPO="$HOME/Documents/GitHub/kevinbrowncodes/spark-cosmos3"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"

echo "Fetching secrets from $SPARK1_USER@$SPARK1 ..."

SECRETS=$(ssh "$SPARK1_USER@$SPARK1" "bash $SPARK1_REPO/scripts/export_secrets.sh")

HF_TOKEN=$(printf '%s\n' "$SECRETS" | grep '^HF_TOKEN=' | cut -d= -f2-)
ANTHROPIC_API_KEY=$(printf '%s\n' "$SECRETS" | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2-)

if [ -z "$HF_TOKEN" ]; then
    echo "ERROR: HF_TOKEN was empty after fetch — check Spark 1's ~/.cache/huggingface/token" >&2
    exit 1
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY was empty after fetch — check Spark 1's .env" >&2
    exit 1
fi

[ -f "$ENV_FILE" ] || cp "$REPO_DIR/.env.example" "$ENV_FILE"

sed -i "s|^HF_TOKEN=.*|HF_TOKEN=$HF_TOKEN|" "$ENV_FILE"
sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY|" "$ENV_FILE"

echo "Done — .env updated (HF_TOKEN: ${#HF_TOKEN} chars, ANTHROPIC_API_KEY: ${#ANTHROPIC_API_KEY} chars)"
