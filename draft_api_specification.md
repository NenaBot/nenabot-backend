# REST API Specification

## Endpoints Overview

| Method     | Endpoint                  | Description                  | Status Code | Notes / Returns                                                        |
| :--------- | :------------------------ | :--------------------------- | :---------- | :--------------------------------------------------------------------- |
| **GET**    | `/health`                 | Basic hardware check.        | 200         | Reports if HW is connected/functional.                                 |
| **GET**    | `/status`                 | Backend service status.      | 200         | Returns `ready`, `busy`, or `error`.                                   |
| **GET**    | `/jobs`                   | List all known jobs.         | 200         | Returns array of all job objects.                                      |
| **GET**    | `/jobs/<ID>`              | Retrieve specific job data.  | 200/404     | Returns full job object for `<ID>`.                                    |
| **GET**    | `/jobs/latest`            | Retrieve latest job data.    | 200/404     | Returns most recent job object.                                        |
| **GET**    | `/profiles`               | List configuration profiles. | 200         | Returns array of available profiles.                                   |
| **GET**    | `/profiles/default`       | Get default profile.         | 200         | Returns the default configuration profile.                             |
| **GET**    | `/jobs/<ID>/image`        | Get job overlay image.       | 200         | Returns annotated JPEG image (base64 or binary).                       |
| **GET**    | `/robot/pose`             | Get robot position.          | 200         | Returns current X, Y, Z, R and joint angles (J1-J4).                   |
| **GET**    | `/streams/camera/feed`    | Camera video feed.           | 200         | MJPEG live raw camera stream.                                          |
| **GET**    | `/streams/detection/feed` | Detection video feed.        | 200         | MJPEG with ArUco markers and contour overlay.                          |
| **POST**   | `/jobs`                   | Initiate a new job.          | 201         | **Body:** `options`, `path`<br>**Returns:** Full job object with `ID`. |
| **POST**   | `/robot/stop`             | Stop active job.             | 200         | Stops running job and halts robot.                                     |
| **POST**   | `/robot/move`             | Move robot.                  | 200         | **Body:** `x`, `y`, `z`, `r`<br>Moves robot to position (calibration). |
| **POST**   | `/streams/camera`         | Start camera stream.         | 201         | Activates raw video feed.                                              |
| **POST**   | `/streams/detection`      | Start detection stream.      | 201         | Activates processed detection feed.                                    |
| **POST**   | `/paths`                  | Generate a path.             | 201         | **Body:** `options`<br>**Returns:** Path object with detections.       |
| **DELETE** | `/streams/camera`         | Stop camera stream.          | 204         | Halts raw video feed.                                                  |
| **DELETE** | `/streams/detection`      | Stop detection stream.       | 204         | Halts detection feed.                                                  |
| **DELETE** | `/jobs/<jobID>`           | Delete job.                  | 204         | Removes job and related data.                                          |

---

## Data Models

### Job Object

The job object encapsulates the configuration, output data, and current processing state.

```json
{
    "options": "string/object",
    "path": "string",
    "log": "string",
    "measurements": [],
    "path-image": "string (url/base64)",
    "status": {
        "lastPointProcessed": "integer",
        "error": "string/null"
    }
}
```
