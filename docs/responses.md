# Real API payloads (captured 2026-06-12, live server)

Captured from the running `cosmos3-api` during an actual pipeline generation.
Prompt text shortened; IDs are real format.

## GET /v1/videos/{id} — job in progress

```json
{
  "model": "/root/.cache/huggingface/hub/models--nvidia--Cosmos3-Nano/snapshots/main",
  "prompt": "<full prompt text echoed back>",
  "id": "video_gen_b32da29e935b46fe877f47f75932c64f",
  "object": "video",
  "status": "in_progress",
  "size": "704x1280",
  "progress": 0,
  "seconds": "4",
  "quality": "default",
  "completed_at": null,
  "created_at": 1781287248,
  "remixed_from_video_id": null,
  "error": null,
  "media_type": "video/mp4",
  "expires_at": null,
  "file_name": null,
  "inference_time_s": null,
  "stage_durations": {},
  "peak_memory_mb": 0.0,
  "action": null
}
```

Notes:
- We submitted `size=720x1280`; the server snapped it to `704x1280`
  (dimension rounding). Expect the echoed size to differ from the request.
- `progress` stayed `0` mid-denoise — do not build UX on it; poll `status`
  and use container logs for real progress.
- `created_at` is a unix timestamp; `seconds` echoes the duration field as a
  string.

## GET /v1/videos — list

```json
{
  "first_id": "video_gen_b32da29e935b46fe877f47f75932c64f",
  "last_id": "video_gen_b32da29e935b46fe877f47f75932c64f",
  "has_more": false,
  "data": [ { "…same job objects as above…": "" } ]
}
```

## Error shape — unknown job id (HTTP 404)

```json
{"error": {"message": "Video not found", "type": "Not Found", "param": null, "code": 404}}
```

## GET /health

`HTTP/1.1 200 OK`, empty body, served by uvicorn. Any response = up;
connection refused = still loading (~3.5 min after container start) or down.
