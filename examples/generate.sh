#!/usr/bin/env bash
# Example: image-to-video generation against the Cosmos 3 Nano API.
# Submits a job, polls until complete, downloads the result.
#
# Usage: ./generate.sh <input_image> "<prompt>" [output.mp4]
#
# Params below match the production settings (Cosmos Technical Report
# Table 21, audio-visual): 50 steps, guidance 6.0, flow_shift 10.0,
# 720x1280 vertical @ 24 fps, guardrails disabled.
#
# GOTCHA: the audio fields are `generate_sound` + `sound_duration`
# (NOT `enable_audio`). All fields are multipart form-data strings.
set -euo pipefail

COSMOS_API="${COSMOS_API_URL:-http://localhost:8000}/v1/videos"
INPUT_IMAGE="${1:?usage: generate.sh <input_image> \"<prompt>\" [output.mp4]}"
PROMPT="${2:?usage: generate.sh <input_image> \"<prompt>\" [output.mp4]}"
OUTPUT="${3:-output.mp4}"

NEG_JSON="$(dirname "$0")/../config/neg.json"
NUM_FRAMES=189          # ≈7.9 s @ 24 fps (clamp: 5–300)
FPS=24

echo "Submitting job to $COSMOS_API ..."
VIDEO_ID=$(curl -sf -X POST "$COSMOS_API" \
    -F "prompt=$PROMPT" \
    -F "negative_prompt=<$NEG_JSON" \
    -F "size=720x1280" \
    -F "num_frames=$NUM_FRAMES" \
    -F "fps=$FPS" \
    -F "generate_sound=true" \
    -F "sound_duration=$(awk "BEGIN{print $NUM_FRAMES/$FPS}")" \
    -F "num_inference_steps=50" \
    -F "guidance_scale=6.0" \
    -F "flow_shift=10.0" \
    -F "max_sequence_length=4096" \
    -F "seed=$RANDOM" \
    -F 'extra_params={"guardrails": false, "use_resolution_template": false, "use_duration_template": false}' \
    -F "input_reference=@$INPUT_IMAGE" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

echo "Queued: id=$VIDEO_ID  (50-step clips take ~50-57 min on the GB10)"

while true; do
    sleep 5
    STATUS_JSON=$(curl -sf "$COSMOS_API/$VIDEO_ID")
    STATUS=$(echo "$STATUS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')
    PROGRESS=$(echo "$STATUS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("progress",0))')
    echo "status=$STATUS ${PROGRESS}%"
    case "$STATUS" in
        completed) break ;;
        failed|error|cancelled)
            echo "Generation $STATUS:" >&2
            echo "$STATUS_JSON" >&2
            exit 1 ;;
    esac
done

echo "Downloading to $OUTPUT ..."
curl -sf "$COSMOS_API/$VIDEO_ID/content" -o "$OUTPUT"
echo "Saved $OUTPUT"
