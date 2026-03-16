---
marp: true
theme: default
paginate: true
title: Nenabot Backend Integration Flow
---

# Nenabot Backend Integration

## Frontend Integration Briefing

Date: Monday integration meeting
Scope: job creation, execution monitoring, and result rendering

---

## Goal Of This Deck

By the end, the frontend team should know:

- Which GET and POST calls are required for the full job flow
- Which data is backend-owned vs frontend-owned
- Exact request and response shapes to use
- How to handle live updates, fallback polling, and common failures

---

## System Context

- API base path is `/api` (FastAPI router prefix)
- Tester UI drives job creation and live execution monitoring
- Results UI is read-only for historical and in-progress jobs
- Robot coordinate conversion happens only in backend

Key source endpoints:

- `POST /api/paths`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}/events` (SSE)
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/image`

---

## End-To-End Sequence

```text
1) Start camera and overlay streams (optional but useful for operator UI)
   GET /api/streams/camera/feed
   GET /api/streams/detection/feed

2) Capture + detect + calibrate
   POST /api/paths

3) User edits pixel path locally on canvas
   (no backend request during editing)

4) Create job from pixel path
   POST /api/jobs

5) Track progress (primary)
   GET /api/jobs/{job_id}/events  [SSE]

6) Fallback if SSE disconnects
   GET /api/jobs/{job_id}         [poll]

7) Read-only results page data
   GET /api/jobs
   GET /api/jobs/{job_id}
   GET /api/jobs/{job_id}/image
```

---

## Ownership: Who Handles What

Backend serves to frontend:

- Detection payload and calibration: `POST /api/paths`
- Created job with robot-space waypoints: `POST /api/jobs`
- Live progress events: `GET /api/jobs/{job_id}/events`
- Persisted status and measurements: `GET /api/jobs/{job_id}`
- Stored clean image: `GET /api/jobs/{job_id}/image`

Frontend owns before job creation:

- Editable `path` in pixel coordinates
- User-selected `workZ`, `workR`, `dryRun`
- Temporary image/calibration/path state

Backend owns after job creation:

- Pixel-to-robot conversion and execution
- Measurement persistence and status transitions
- SSE event publication and terminal state

---

## Endpoint Matrix (What FE Needs)

| Purpose            | Method + Path                     | FE sends                                | FE receives                             | Required for MVP |
| ------------------ | --------------------------------- | --------------------------------------- | --------------------------------------- | ---------------- |
| Detect + calibrate | `POST /api/paths`                 | `{ options }`                           | detections, image, markers, calibration | Yes              |
| Create job         | `POST /api/jobs`                  | pixel path + work coords + mode + image | created job                             | Yes              |
| Live progress      | `GET /api/jobs/{job_id}/events`   | none                                    | SSE event stream                        | Yes              |
| Polling fallback   | `GET /api/jobs/{job_id}`          | none                                    | full job snapshot                       | Yes              |
| Job list           | `GET /api/jobs`                   | none                                    | array of jobs                           | Yes              |
| Base image         | `GET /api/jobs/{job_id}/image`    | none                                    | image/jpeg bytes                        | Yes              |
| Stop running job   | `POST /api/robot/stop`            | none                                    | `{ stopped: boolean }`                  | Yes              |
| Debug pose         | `GET /api/robot/pose`             | none                                    | current robot pose                      | Optional         |
| Debug move         | `POST /api/robot/move`            | robot xyzr                              | command result                          | Optional         |
| Camera stream      | `GET /api/streams/camera/feed`    | none                                    | MJPEG stream                            | Optional         |
| Detection stream   | `GET /api/streams/detection/feed` | none                                    | MJPEG stream                            | Optional         |

---

## POST /api/paths

Purpose:

- Capture clean image
- Detect objects and marker corners
- Capture calibration from current robot pose

Example request:

```json
{
    "options": {}
}
```

Example response (trimmed):

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
            "width_mm": 18.0,
            "height_mm": 18.0,
            "center_x": 473.6,
            "center_y": 242.6
        }
    ],
    "image_base64": "...",
    "pixelsPerMm": 6.42,
    "markerCount": 1,
    "markerCorners": [
        {
            "corners": [
                { "x": 128.0, "y": 90.0 },
                { "x": 162.0, "y": 91.0 },
                { "x": 161.0, "y": 125.0 },
                { "x": 127.0, "y": 124.0 }
            ]
        }
    ],
    "calibration": {
        "calibrated": true,
        "robotStart": { "x": 203.4, "y": -116.2, "z": 12.0, "r": 0.0 },
        "canvasStart": { "x": 144.0, "y": 427.0 },
        "pixelsPerMm": 6.42
    },
    "error": null,
    "options": {}
}
```

---

## Frontend Handling After POST /api/paths

Must store locally:

- `detections` (for initial path build)
- `image_base64` (send later as `imageBase64` when creating job)
- `markerCorners` (overlay diagnostics)
- `calibration` object (gating rule for Start button)

Must do before enabling Start:

- Confirm `calibration.calibrated === true`
- Confirm there is at least one pixel waypoint in local path

Important behavior:

- Calibration is captured only during `POST /api/paths`
- User should click Detect while robot is at intended start position

---

## Frontend Point Selection Logic (Current Tester)

Path source before manual edits:

- For each detection, if 4 corners exist, all 4 corners are appended as waypoints
- If corners are missing, fallback is one waypoint at detection center
- Result is stored in local `detectedPath` as pixel points only

Tool modes in the canvas:

- Move mode: drag existing waypoint
- Add mode: insert a new waypoint at clicked pixel location
- Delete mode: remove nearest waypoint near click

No API call happens while selecting, dragging, adding, or deleting points.

---

## Point Interaction Rules To Match

Selection threshold:

- Nearest waypoint hit test uses distance threshold of about 14 px

Move behavior:

- On mouse down in Move mode, nearest point inside threshold is selected
- During mouse move, selected point coordinates are continuously updated
- On mouse up or mouse leave, dragging stops

Add behavior:

- New point is inserted after the nearest existing point index
- If path has fewer than 2 points, append at end

Delete behavior:

- Nearest point within threshold is removed

---

## X And Y Coordinate System (Frontend Canvas)

Canvas pixel origin:

- Start point is top-left of the canvas/image: x=0, y=0
- x increases to the right
- y increases downward

Important for responsive UI:

- Mouse events come in CSS/display pixels
- Waypoints are stored in canvas image pixels
- Convert using scale factors so points stay accurate at any screen size:

$$
scaleX = \frac{canvas.width}{rect.width}, \quad scaleY = \frac{canvas.height}{rect.height}
$$

$$
x = (clientX - rect.left) \cdot scaleX, \quad y = (clientY - rect.top) \cdot scaleY
$$

---

## How To Draw Correctly On Screen

Rendering order used by current tester:

1. Draw base snapshot image first.
2. Draw detection and marker overlays.
3. Draw waypoint path line.
4. Draw waypoint circles and labels.
5. Draw calibration start marker.

Coordinate consistency rules:

- Keep all draw calls in the same pixel coordinate space as stored waypoints.
- If image loads, set canvas intrinsic size to image size before drawing.
- Do not store CSS-scaled coordinates in path state.

Backend conversion reference (after POST /jobs):

$$
dpx = px - canvasStartX, \quad dpy = py - canvasStartY
$$

$$
robotX = robotStartX - \frac{dpy}{pixelsPerMm}, \quad robotY = robotStartY - \frac{dpx}{pixelsPerMm}
$$

So frontend keeps pixel-space x/y, backend applies calibration to get robot-space mm.

---

## What Gets Sent After Point Editing

At Start or Dry Run, frontend creates request body from current local state:

```json
{
    "path": [
        { "x": 444.2, "y": 212.8 },
        { "x": 470.0, "y": 220.0 },
        { "x": 503.0, "y": 272.4 }
    ],
    "workZ": 0.0,
    "workR": 0.0,
    "dryRun": false,
    "imageBase64": "..."
}
```

Important:

- `path` reflects the latest user-edited point order
- Points are still pixel-space here; backend converts to robot-space
- Keep local pixel path for UI rendering/editing even after job creation

---

## POST /api/jobs

Purpose:

- Create and immediately start a job in background
- Convert frontend pixel points into robot-space waypoints in backend

Example request:

```json
{
    "path": [
        { "x": 444.2, "y": 212.8 },
        { "x": 502.6, "y": 213.1 },
        { "x": 503.0, "y": 272.4 }
    ],
    "workZ": 0.0,
    "workR": 0.0,
    "dryRun": false,
    "imageBase64": "..."
}
```

Failure to handle:

- `409 Conflict` when not calibrated yet

```json
{
    "detail": "Not calibrated - call POST /paths first (with robot arm at starting position)"
}
```

---

## POST /api/jobs Response (Created Job)

Example response (trimmed):

```json
{
    "id": "4c7a8bd1-12d4-4a9b-a47d-b40c5ce7cc44",
    "options": null,
    "path": [
        { "x": 203.4, "y": -116.2, "z": 0.0, "r": 0.0 },
        { "x": 203.4, "y": -125.3, "z": 0.0, "r": 0.0 },
        { "x": 194.1, "y": -125.3, "z": 0.0, "r": 0.0 }
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

Frontend note:

- Returned `path` is robot-space (mm), not the original pixel points
- Keep local pixel path if you still need editable canvas data in current page state

---

## Live Monitoring: GET /api/jobs/{job_id}/events (SSE)

Connection behavior:

- First event is always `job:snapshot`
- Then progress events like `job:waypoint_started` and `job:waypoint_completed`
- Terminal event is one of `job:completed`, `job:failed`, `job:stopped`
- Stream closes after terminal event

Example SSE frames:

```text
event: job:snapshot
data: {"type":"job:snapshot","jobId":"4c7...","state":"running","lastPointProcessed":0,"totalPoints":3,"error":null,"timestamp":"2026-03-14T10:31:02.125Z"}

event: job:waypoint_completed
data: {"type":"job:waypoint_completed","jobId":"4c7...","state":"running","lastPointProcessed":1,"totalPoints":3,"waypointIndex":0,"measurement":{"waypointIndex":0,"waypoint":{"x":203.4,"y":-116.2,"z":0.0,"r":0.0},"pixelX":444.2,"pixelY":212.8,"scanResult":null,"simulated":false,"timestamp":"2026-03-14T10:31:08.300Z"},"timestamp":"2026-03-14T10:31:08.301Z"}

event: job:completed
data: {"type":"job:completed","jobId":"4c7...","state":"completed","lastPointProcessed":3,"totalPoints":3,"error":null,"timestamp":"2026-03-14T10:31:15.002Z"}
```

---

## Polling Fallback: GET /api/jobs/{job_id}

When to poll:

- SSE connection error
- Legacy clients without EventSource support

Polling cadence used now:

- Tester flow: about every 800 ms during fallback
- Results page: about every 1200 ms while selected job is running

Example response (trimmed):

```json
{
    "id": "4c7a8bd1-12d4-4a9b-a47d-b40c5ce7cc44",
    "dryRun": false,
    "path": [{ "x": 203.4, "y": -116.2, "z": 0.0, "r": 0.0 }],
    "measurements": [
        {
            "waypointIndex": 0,
            "waypoint": { "x": 203.4, "y": -116.2, "z": 0.0, "r": 0.0 },
            "pixelX": 444.2,
            "pixelY": 212.8,
            "scanResult": null,
            "simulated": false,
            "timestamp": "2026-03-14T10:31:08.300Z"
        }
    ],
    "status": {
        "state": "running",
        "lastPointProcessed": 1,
        "error": null
    }
}
```

---

## Results Image: GET /api/jobs/{job_id}/image

Response type:

- `image/jpeg` binary bytes

Important rendering pattern:

- Backend stores clean base image only
- Frontend draws overlays (measurement markers) client-side
- Use measurement `pixelX` and `pixelY` to place circles on canvas

Minimal browser usage:

```js
const url = `${apiBase}/api/jobs/${jobId}/image`;
img.src = url;
// Then draw measurement overlays from GET /jobs/{job_id}.measurements[*].pixelX/pixelY
```

---

## Naming And Contract Rules

Use these field names exactly (camelCase in JSON):

- Request to `POST /api/jobs`: `workZ`, `workR`, `dryRun`, `imageBase64`
- Path response aliases: `pixelsPerMm`, `markerCount`, `markerCorners`
- Calibration aliases: `robotStart`, `canvasStart`, `pixelsPerMm`
- Job status alias: `lastPointProcessed`
- Measurement aliases: `waypointIndex`, `pixelX`, `pixelY`, `scanResult`

Integration risk if mismatched:

- Snake_case client fields may be ignored or parsed incorrectly

---

## Frontend Implementation Checklist

1. Start optional streams for operator visibility.
2. Call `POST /api/paths` and store `image_base64`, `detections`, `calibration`.
3. Build/edit local pixel path only in browser state.
4. Block Start button unless calibrated and path not empty.
5. Call `POST /api/jobs` with pixel path + work coords + mode + image.
6. Subscribe to SSE endpoint for progress and incremental measurement updates.
7. On SSE error, switch to polling `GET /api/jobs/{job_id}`.
8. For results, fetch `GET /api/jobs`, `GET /api/jobs/{job_id}`, and image endpoint.
9. Draw overlays from `measurement.pixelX` and `measurement.pixelY` on the base image.
10. Handle `stopped`, `failed`, and `completed` as terminal states.

---

## Quick Meeting Script (Suggested)

- Detect first, because calibration is captured only in `POST /api/paths`.
- Frontend edits only pixel points; backend owns coordinate conversion and robot execution.
- Job creation is one POST that also starts execution immediately.
- Primary progress channel is SSE; polling is a resilience fallback.
- Results page is read-only and reconstructs overlays from stored pixel coordinates.

---

## Appendix: Copy/Paste Request Samples

Detect:

```bash
curl -X POST http://localhost:8000/api/paths \
  -H "Content-Type: application/json" \
  -d '{"options":{}}'
```

Create job:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "path":[{"x":444.2,"y":212.8},{"x":502.6,"y":213.1}],
    "workZ":0.0,
    "workR":0.0,
    "dryRun":true,
    "imageBase64":"..."
  }'
```
