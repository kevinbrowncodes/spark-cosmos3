#!/usr/bin/env bash
# Check vendored upsampler data files against upstream sha256 checksums.
#
# Re-fetches the upstream raw files listed in data/SOURCES.md and compares
# their sha256 against the recorded values. Exits non-zero if any file has
# drifted, so you can decide whether to re-vendor.
#
# Usage:
#   ./scripts/check_upsampler_sources.sh
#
# Requires: curl, sha256sum (or shasum -a 256 on macOS)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# sha256sum compatibility (Linux vs macOS)
sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

# Upstream raw URLs and expected checksums (from data/SOURCES.md)
TEMPLATE_URL="https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_prompt.txt"
TEMPLATE_SHA="bc96ddc77589ad6bd67868bbbc01e9cc881bb13e9b267c77f93aa79d15e32948"

SCHEMA_URL="https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompting_templates/external_api/t2v_i2v_video_json_schema.json"
SCHEMA_SHA="71dec36058538e5b99649fcc81d2c19fd48cb0a701e0510af1f443552052c797"

RRD_URL="https://raw.githubusercontent.com/nvidia/cosmos-framework/main/cosmos_framework/inference/prompt_upsampling.py"
RRD_SHA="9e120a0436403ae3f82f22b5158d4409987e9453c2eb69654ca382e179c74942"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

drift=0

check_file() {
    local label="$1" url="$2" expected="$3" tmpfile="$TMPDIR/$(basename "$url")"
    echo -n "checking $label ... "
    curl -sSf "$url" -o "$tmpfile"
    actual="$(sha256 "$tmpfile")"
    if [ "$actual" = "$expected" ]; then
        echo "OK ($actual)"
    else
        echo "DRIFT"
        echo "  expected: $expected"
        echo "  upstream: $actual"
        drift=1
    fi
}

check_file "upsampler_template.txt" "$TEMPLATE_URL" "$TEMPLATE_SHA"
check_file "upsampler_schema.json"  "$SCHEMA_URL"   "$SCHEMA_SHA"
check_file "prompt_upsampling.py (RRD source)" "$RRD_URL" "$RRD_SHA"

if [ "$drift" -ne 0 ]; then
    echo ""
    echo "One or more vendored files have drifted from upstream."
    echo "Review the upstream changes and decide whether to re-vendor."
    echo "If re-vendoring: update data/, regenerate gateway/tests/fixtures/, update data/SOURCES.md."
    exit 1
fi

echo ""
echo "All vendored files match upstream checksums."
