# REST API Specification

All endpoints are prefixed with `/api`.

## Endpoints Overview

| Method     | Endpoint                      | Description                        | Status Code | Notes / Returns                                                        |
| :--------- | :---------------------------- | :--------------------------------- | :---------- | :--------------------------------------------------------------------- |
| **GET**    | `/api/health`                 | Basic hardware check.              | 200         | Reports if HW is connected/functional.                                 |
| **GET**    | `/api/status`                 | Backend service status.            | 200         | Returns `ready`, `busy`, or `error`.                                   |
| **GET**    | `/api/jobs`                   | List all known jobs.               | 200         | Returns array of all job objects.                                      |
| **GET**    | `/api/jobs/<ID>`              | Retrieve specific job data.        | 200/404     | Returns full job object for `<ID>`.                                    |
| **GET**    | `/api/jobs/latest`            | Retrieve latest job data.          | 200/404     | Returns most recent job object.                                        |
| **GET**    | `/api/jobs/<ID>/events`       | SSE stream of job progress events. | 200         | `text/event-stream` — real-time updates (see SSE Events below).        |
| **GET**    | `/api/profiles`               | List configuration profiles.       | 200         | Returns array of available profiles.                                   |
| **GET**    | `/api/profiles/default`       | Get default profile.               | 200         | Returns the default configuration profile.                             |
| **GET**    | `/api/jobs/<ID>/image`        | Get job overlay image.             | 200         | Returns annotated JPEG image (base64 or binary).                       |
| **GET**    | `/api/robot/pose`             | Get robot position.                | 200         | Returns current X, Y, Z, R and joint angles (J1-J4).                   |
| **GET**    | `/api/streams/camera/feed`    | Camera video feed.                 | 200         | MJPEG live raw camera stream.                                          |
| **GET**    | `/api/streams/detection/feed` | Detection video feed.              | 200         | MJPEG with ArUco markers and contour overlay.                          |
| **POST**   | `/api/jobs`                   | Initiate a new job.                | 201         | **Body:** `options`, `path`<br>**Returns:** Full job object with `ID`. |
| **POST**   | `/api/robot/stop`             | Stop active job.                   | 200         | Stops running job and halts robot.                                     |
| **POST**   | `/api/robot/move`             | Move robot.                        | 200         | **Body:** `x`, `y`, `z`, `r`<br>Moves robot to position (calibration). |
| **POST**   | `/api/paths`                  | Generate a path.                   | 201         | **Body:** `options`<br>**Returns:** Path object with detections.       |
| **DELETE** | `/api/jobs/<jobID>`           | Delete job.                        | 204         | Removes job and related data.                                          |

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

## SSE Job Events — `GET /api/jobs/<ID>/events`

Real-time job progress is delivered via Server-Sent Events on this endpoint.

The event types, payload schemas, and full documentation are included in the
OpenAPI specification and visible in the interactive Swagger UI at `/api/docs`.
