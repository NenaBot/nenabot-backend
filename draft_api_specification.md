# REST API Specification

All endpoints are prefixed with `/api`.

## Endpoints Overview

| Method     | Endpoint                     | Description                        | Status Code | Notes / Returns                                                                                    |
| :--------- | :--------------------------- | :--------------------------------- | :---------- | :------------------------------------------------------------------------------------------------- |
| **GET**    | `/api/health`                | Basic hardware check.              | 200         | Reports if HW is connected/functional.                                                             |
| **GET**    | `/api/status`                | Backend service status.            | 200         | Returns `ready`, `busy`, or `error`.                                                               |
| **GET**    | `/api/job`                   | List all known jobs.               | 200         | Returns array of all job objects.                                                                  |
| **GET**    | `/api/job/<ID>`              | Retrieve specific job data.        | 200/404     | Returns full job object for `<ID>`.                                                                |
| **GET**    | `/api/job/latest`            | Retrieve latest job data.          | 200/404     | Returns most recent job object.                                                                    |
| **GET**    | `/api/job/<ID>/events`       | SSE stream of job progress events. | 200         | `text/event-stream` — real-time updates (see SSE Events below).                                    |
| **GET**    | `/api/job/<ID>/image`        | Get job base image.                | 200         | Returns clean JPEG snapshot (no annotations).                                                      |
| **GET**    | `/api/profile`               | List configuration profiles.       | 200         | Returns array of available profiles.                                                               |
| **GET**    | `/api/profile/default`       | Get default profile.               | 200         | Returns the default configuration profile.                                                         |
| **GET**    | `/api/robot/pose`            | Get robot position.                | 200         | Returns current X, Y, Z, R and joint angles (J1-J4).                                               |
| **GET**    | `/api/stream/camera/feed`    | Camera video feed.                 | 200         | MJPEG live raw camera stream.                                                                      |
| **GET**    | `/api/stream/detection/feed` | Detection video feed.              | 200         | MJPEG with ArUco markers and contour overlay.                                                      |
| **POST**   | `/api/job`                   | Initiate a new job.                | 201         | **Body:** `options`, `path`, `workZ`, `workR`, `dryRun`<br>**Returns:** Full job object with `ID`. |
| **POST**   | `/api/path/detect`           | Detect battery path & calibrate.   | 201         | **Body:** `options`<br>**Returns:** Detections sorted by nearest-neighbor.                         |
| **POST**   | `/api/path`                  | Check/optimize path order.         | 200         | **Body:** `waypoints`<br>**Returns:** Waypoints sorted from canvas start.                          |
| **POST**   | `/api/robot/move`            | Move robot.                        | 200         | **Body:** `x`, `y`, `z`, `r`<br>Moves robot to position (calibration).                             |
| **POST**   | `/api/robot/stop`            | Stop active job.                   | 200         | Stops running job and halts robot.                                                                 |
| **DELETE** | `/api/job/<jobID>`           | Delete job.                        | 204         | Removes job and related data.                                                                      |

---

## Data Models

### Job Object

The job object encapsulates the configuration, output data, and current processing state.

```json
{
    "id": "string (uuid)",
    "options": "object | null",
    "path": [{ "x": 0.0, "y": 0.0, "z": 0.0, "r": 0.0 }],
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

## Path Detection & Sorting

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
                { "x": 100.0, "y": 100.0 },
                { "x": 200.0, "y": 100.0 },
                { "x": 200.0, "y": 200.0 },
                { "x": 100.0, "y": 200.0 }
            ],
            "width_mm": 85.5,
            "height_mm": 92.3,
            "center_x": 150.0,
            "center_y": 150.0
        }
    ],
    "detections_sorted": "boolean — true if detections are ordered by nearest-neighbor from canvas start",
    "image_base64": "string (full JPEG as base64)",
    "pixels_per_mm": 2.5,
    "marker_count": 1,
    "marker_corners": [
        {
            "corners": [
                { "x": 50.0, "y": 50.0 },
                { "x": 100.0, "y": 50.0 },
                { "x": 100.0, "y": 100.0 },
                { "x": 50.0, "y": 100.0 }
            ]
        }
    ],
    "calibration": {
        "calibrated": true,
        "robot_start": { "x": 100.0, "y": 200.0, "z": 0.0, "r": 0.0 },
        "canvas_start": { "x": 640.0, "y": 450.0 },
        "pixels_per_mm": 2.5
    },
    "error": null
}
```

**Key behavior:**

- **Detections are auto-sorted** by nearest-neighbor algorithm starting from the `canvas_start` point (which is **50mm below the first ArUco marker center** to account for robot arm offset).
- Canvas start = marker center + (50mm × pixels_per_mm) in Y direction.
- Sorting ensures the optimal inspection path when accepted.

---

### **POST** `/api/path` — Optimize/check path

**Request:**

```json
{
    "waypoints": [
        { "x": 100.0, "y": 100.0 },
        { "x": 700.0, "y": 400.0 },
        { "x": 650.0, "y": 400.0 }
    ]
}
```

**Response (200):**

```json
{
    "path": [
        { "x": 100.0, "y": 100.0 },
        { "x": 650.0, "y": 400.0 },
        { "x": 700.0, "y": 400.0 }
    ]
}
```

**Key behavior:**

- Reorders input waypoints using nearest-neighbor algorithm from the stored `canvas_start` point.
- Useful for optimizing custom paths before job submission.
- Requires prior calibration (status **409** if not calibrated).

---

## SSE Job Events — `GET /api/job/<ID>/events`

Real-time job progress is delivered via Server-Sent Events on this endpoint.

The event types, payload schemas, and full documentation are included in the
OpenAPI specification and visible in the interactive Swagger UI at `/api/docs`.
