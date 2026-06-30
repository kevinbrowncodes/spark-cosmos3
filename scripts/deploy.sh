#!/usr/bin/env bash
# Build and start the gateway and progress-sidecar with the current git SHA
# baked in as a Docker label, then start (or restart) the full stack.
#
# Usage: ./scripts/deploy.sh
#
# To verify after deploy:
#   docker inspect spark-cosmos3-gateway:latest | python3 -c \
#     "import sys,json; d=json.load(sys.stdin); print(d[0]['Config']['Labels'])"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

export GIT_SHA
GIT_SHA=$(git rev-parse --short HEAD)

echo "Deploying spark-cosmos3 @ $GIT_SHA ..."
docker compose up -d --build --no-deps gateway progress
docker compose up -d cosmos3

echo
echo "Done. Verify labels:"
echo "  Gateway : $(docker inspect spark-cosmos3-gateway:latest | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Labels'])")"
echo "  Progress: $(docker inspect spark-cosmos3-progress:latest | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Labels'])")"
