# REST API Specification

All endpoints are prefixed with `/api`.

## Endpoints Overview

| Method     | Endpoint                     | Description                          | Status Code | Notes / Returns                                                                                    |
| :--------- | :--------------------------- | :----------------------------------- | :---------- | :------------------------------------------------------------------------------------------------- |
| **GET**    | `/api/health`                | Basic hardware check.                | 200         | Reports if HW is connected/functional.                                                             |
| **GET**    | `/api/status`                | Backend service status.              | 200         | Returns `ready`, `busy`, or `error`.                                                               |
| **GET**    | `/api/job`                   | List all known jobs.                 | 200         | Returns array of all job objects.                                                                  |
| **GET**    | `/api/job/<ID>`              | Retrieve specific job data.          | 200/404     | Returns full job object for `<ID>`.                                                                |
| **GET**    | `/api/job/latest`            | Retrieve latest job data.            | 200/404     | Returns most recent job object.                                                                    |
| **GET**    | `/api/job/<ID>/events`       | SSE stream of job progress events.   | 200         | `text/event-stream` — real-time updates (see SSE Events below).                                    |
| **GET**    | `/api/job/<ID>/image`        | Get job base image.                  | 200         | Returns clean JPEG snapshot (no annotations).                                                      |
| **GET**    | `/api/profile`               | List configuration profiles.         | 200         | Returns array of available profiles.                                                               |
| **GET**    | `/api/profile/default`       | Get default profile.                 | 200         | Returns the default configuration profile.                                                         |
| **GET**    | `/api/robot/pose`            | Get robot position.                  | 200         | Returns current X, Y, Z, R and joint angles (J1-J4).                                               |
| **GET**    | `/api/stream/camera/feed`    | Camera video feed.                   | 200         | MJPEG live raw camera stream.                                                                      |
| **GET**    | `/api/stream/detection/feed` | Detection video feed.                | 200         | MJPEG with ArUco markers and contour overlay.                                                      |
| **POST**   | `/api/job`                   | Initiate a new job.                  | 201         | **Body:** `options`, `path`, `workZ`, `workR`, `dryRun`<br>**Returns:** Full job object with `ID`. |
| **POST**   | `/api/path/detect`           | Detect battery path & calibrate.     | 201         | **Body:** `options`<br>**Returns:** Detections ordered by distance from canvas start.              |
| **POST**   | `/api/path/populate`         | Populate perimeter measurement path. | 200         | **Body:** `batteries`, `measuringPointsPerCm`<br>**Returns:** indexed measurement points.          |
| **POST**   | `/api/robot/move`            | Move robot.                          | 200         | **Body:** `x`, `y`, `z`, `r`<br>Moves robot to position (calibration).                             |
| **POST**   | `/api/robot/stop`            | Stop active job.                     | 200         | Stops running job and halts robot.                                                                 |
| **DELETE** | `/api/job/<jobID>`           | Delete job.                          | 204         | Removes job and related data.                                                                      |

---

## Data Models

### Job Create Path Point

`POST /api/job` accepts path points from either manual points or `/api/path/populate` output.
Pixel coordinates from the image/canvas are distinct from robot millimeter coordinates.

```json
{
    "pixelX": 650.0,
    "pixelY": 390.0,
    "index": "0-0-0",
    "batteryNr": 0,
    "cornerIndex": 0,
    "measurementIndex": 0
}
```

Canonical request fields are `pixelX` and `pixelY`.

When index metadata is provided, it is persisted with the job waypoints and returned in `GET /api/job` and `GET /api/job/<ID>` responses.

Job responses use explicit robot fields (`robotX`,`robotY`,`robotZ`,`robotR`) so robot and pixel coordinates are clearly distinct.

### Job Object

The job object encapsulates the configuration, output data, and current processing state.

```json
{
    "id": "string (uuid)",
    "options": "object | null",
    "path": [{ "robotX": 0.0, "robotY": 0.0, "robotZ": 0.0, "robotR": 0.0 }],
    "dryRun": false,
    "measurements": [],
    "status": {
        "state": "created | running | completed | failed | stopped",
        "lastPointProcessed": 0,
        "error": "string | null"
    }
}
```

---

## Path Detection & Population

### **POST** `/api/path/detect` — Detect path & calibrate

**Request:**

```json
{
    "options": {}
}
```

**Response (201):**

```json
{
    "ok": true,
    "detections": [
        {
            "corners": [
                { "pixelX": 100.0, "pixelY": 100.0 },
                { "pixelX": 200.0, "pixelY": 100.0 },
                { "pixelX": 200.0, "pixelY": 200.0 },
                { "pixelX": 100.0, "pixelY": 200.0 }
            ],
            "width_mm": 85.5,
            "height_mm": 92.3,
            "pixelCenterX": 150.0,
            "pixelCenterY": 150.0,
            "confidence": 0.95
        }
    ],
    "detections_sorted": "boolean — true if detections are ordered by nearest-neighbor from canvas start",
    "image_base64": "string (full JPEG as base64)",
    "pixels_per_mm": 2.5,
    "marker_count": 1,
    "marker_corners": [
        {
            "corners": [
                { "pixelX": 50.0, "pixelY": 50.0 },
                { "pixelX": 100.0, "pixelY": 50.0 },
                { "pixelX": 100.0, "pixelY": 100.0 },
                { "pixelX": 50.0, "pixelY": 100.0 }
            ]
        }
    ],
    "calibration": {
        "calibrated": true,
        "robot_start": {
            "robotX": 100.0,
            "robotY": 200.0,
            "robotZ": 0.0,
            "robotR": 0.0
        },
        "canvas_start": { "pixelX": 640.0, "pixelY": 450.0 },
        "pixels_per_mm": 2.5
    },
    "error": null
}
```

**Key behavior:**

- **Detections are sorted by direct distance from `canvas_start`** (closest battery first).
- Pixel coordinates are represented as `pixelX`/`pixelY` in path-related payloads.
- Canvas start = marker center + (50mm × pixels_per_mm) in Y direction.
- The response includes calibration data required for path population and job creation.

---

### **POST** `/api/path/populate` — Populate perimeter points

**Request:**

```json
{
    "measuringPointsPerCm": 0.5,
    "batteries": [
        {
            "corners": [
                { "pixelX": 650.0, "pixelY": 390.0 },
                { "pixelX": 690.0, "pixelY": 390.0 },
                { "pixelX": 690.0, "pixelY": 430.0 },
                { "pixelX": 650.0, "pixelY": 430.0 }
            ]
        }
    ]
}
```

**Response (200):**

```json
{
    "path": [
        {
            "index": "0-0-0",
            "batteryNr": 0,
            "cornerIndex": 0,
            "measurementIndex": 0,
            "pixelX": 650.0,
            "pixelY": 390.0
        }
    ]
}
```

**Key behavior:**

- Canonical coordinate keys are `pixelX` and `pixelY`.
- Generates points on each battery perimeter only (no interior fill).
- Density is controlled by `measuringPointsPerCm`.
- Each battery traversal starts at the corner nearest to `canvas_start`, then proceeds clockwise.
- Batteries are ordered by nearest distance from `canvas_start` (not by shortest route between batteries).
- Requires prior calibration (status **409** if not calibrated).

---

## SSE Job Events — `GET /api/job/<ID>/events`

Real-time job progress is delivered via Server-Sent Events on this endpoint.

The event types, payload schemas, and full documentation are included in the
OpenAPI specification and visible in the interactive Swagger UI at `/api/docs`.
