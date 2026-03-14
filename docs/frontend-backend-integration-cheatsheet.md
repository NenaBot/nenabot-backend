# Frontend Backend Integration Cheatsheet

This is a compact handoff reference for implementing the Nenabot frontend against the current backend.

## Base

- Base URL: `http://localhost:8000`
- API prefix: `/api`

## Required Calls In Order

1. Optional preview streams:
- `GET /api/streams/camera/feed`
- `GET /api/streams/detection/feed`

2. Detect and calibrate:
- `POST /api/paths`

3. Create and start job:
- `POST /api/jobs`

4. Monitor live progress:
- Primary: `GET /api/jobs/{job_id}/events` (SSE)
- Fallback: `GET /api/jobs/{job_id}` (poll)

5. Results page data:
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/image`

## Data Handling Rules

Frontend local state before `POST /jobs`:

- `detectedPath`: editable pixel points
- `image_base64` from `/paths` response
- `calibration` from `/paths` response
- Marker/detection metadata for overlay UI

Send to backend on `POST /jobs`:

- `path`: array of pixel points `{x, y}`
- `workZ`, `workR`, `dryRun`
- `imageBase64`: clean snapshot from `/paths`

Do not do in frontend:

- Do not convert pixel to robot coordinates
- Do not assume calibration persists unless `/paths` succeeded in current session

Backend behavior to rely on:

- Converts pixel path to robot waypoints
- Stores clean image and pixel path for overlays
- Emits SSE progress events
- Persists measurements with `pixelX` and `pixelY`

## Contracts To Match Exactly

Use these exact JSON keys:

- Job create request: `workZ`, `workR`, `dryRun`, `imageBase64`
- Path response keys: `pixelsPerMm`, `markerCount`, `markerCorners`
- Calibration keys: `robotStart`, `canvasStart`, `pixelsPerMm`
- Job status key: `lastPointProcessed`
- Measurement keys: `waypointIndex`, `pixelX`, `pixelY`, `scanResult`

## Example Requests And Responses

### POST /api/paths

Request:

```json
{
  "options": {}
}
```

Response (trimmed):

```json
{
  "ok": true,
  "detections": [
    {
      "corners": [
        { "x": 444.2, "y": 212.8 },
        { "x": 502.6, "y": 213.1 },
        { "x": 503.0, "y": 272.4 },
        { "x": 444.6, "y": 272.0 }
      ],
      "center_x": 473.6,
      "center_y": 242.6,
      "confidence": 0.97
    }
  ],
  "image_base64": "...",
  "pixelsPerMm": 6.42,
  "markerCount": 1,
  "markerCorners": [{ "corners": [{ "x": 128, "y": 90 }] }],
  "calibration": {
    "calibrated": true,
    "robotStart": { "x": 203.4, "y": -116.2, "z": 12.0, "r": 0.0 },
    "canvasStart": { "x": 144.0, "y": 427.0 },
    "pixelsPerMm": 6.42
  }
}
```

### POST /api/jobs

Request:

```json
{
  "path": [
    { "x": 444.2, "y": 212.8 },
    { "x": 502.6, "y": 213.1 }
  ],
  "workZ": 0.0,
  "workR": 0.0,
  "dryRun": false,
  "imageBase64": "..."
}
```

Success response (trimmed):

```json
{
  "id": "4c7a8bd1-12d4-4a9b-a47d-b40c5ce7cc44",
  "path": [
    { "x": 203.4, "y": -116.2, "z": 0.0, "r": 0.0 },
    { "x": 203.4, "y": -125.3, "z": 0.0, "r": 0.0 }
  ],
  "dryRun": false,
  "measurements": [],
  "status": {
    "state": "running",
    "lastPointProcessed": 0,
    "error": null
  }
}
```

Failure response (not calibrated):

```json
{
  "detail": "Not calibrated - call POST /paths first (with robot arm at starting position)"
}
```

### GET /api/jobs/{job_id}/events (SSE)

Typical event sequence:

- `job:snapshot`
- `job:started`
- `job:waypoint_started`
- `job:waypoint_completed` (includes measurement)
- terminal: `job:completed` or `job:failed` or `job:stopped`

SSE sample frame:

```text
event: job:waypoint_completed
data: {"type":"job:waypoint_completed","jobId":"4c7...","state":"running","lastPointProcessed":1,"totalPoints":3,"waypointIndex":0,"measurement":{"waypointIndex":0,"pixelX":444.2,"pixelY":212.8,"simulated":false},"timestamp":"2026-03-14T10:31:08.301Z"}
```

### GET /api/jobs/{job_id} and /image

- `GET /api/jobs/{job_id}` returns status + measurements (with `pixelX`, `pixelY`)
- `GET /api/jobs/{job_id}/image` returns `image/jpeg`

Render strategy:

1. Show image bytes as base layer.
2. Draw circles at each measurement `pixelX`/`pixelY`.
3. Keep polling while job state is `running`.

## Recommended UI Guardrails

- Disable Start button until both are true:
- `calibration.calibrated === true`
- `path.length > 0`

- On SSE error:
- close EventSource
- start polling `GET /api/jobs/{job_id}` every 800 ms to 1200 ms

- Terminal states to handle explicitly:
- `completed`
- `failed`
- `stopped`

## Minimal Curl Set

```bash
curl -X POST http://localhost:8000/api/paths -H "Content-Type: application/json" -d '{"options":{}}'

curl -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d '{"path":[{"x":444.2,"y":212.8}],"workZ":0,"workR":0,"dryRun":true,"imageBase64":"..."}'

curl http://localhost:8000/api/jobs
curl http://localhost:8000/api/jobs/<job_id>
curl http://localhost:8000/api/jobs/<job_id>/image --output job.jpg
```
