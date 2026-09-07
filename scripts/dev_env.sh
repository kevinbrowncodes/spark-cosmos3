#!/usr/bin/env bash
# Local test environment. The host Python is PEP 668-locked, so tests run from
# a venv layered over the system site-packages. flow-protocol is pinned to
# FLOW_VERSION from .env (default v0.1.0) so the UI pin has exactly one home.
#
# Usage: ./scripts/dev_env.sh
#   then: .venv/bin/python -m pytest --cov=flow --cov-fail-under=95
set -euo pipefail
cd "$(dirname "$0")/.."

FLOW_VERSION="${FLOW_VERSION:-$(grep -E '^FLOW_VERSION=' .env 2>/dev/null | cut -d= -f2 || true)}"
FLOW_VERSION="${FLOW_VERSION:-v0.1.0}"

python3 -m venv --system-site-packages .venv
.venv/bin/pip install --disable-pip-version-check -q -r requirements-dev.txt \
  "flow-protocol[server] @ git+https://github.com/kevinbrowncodes/flow@${FLOW_VERSION}#subdirectory=protocol/python"
echo "ready (flow-protocol ${FLOW_VERSION}): .venv/bin/python -m pytest --cov=flow --cov-fail-under=95"
