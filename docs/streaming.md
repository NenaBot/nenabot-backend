# Video Streaming

Nenabot exposes two MJPEG streams:

| Stream | Endpoint | Description |
| :--- | :--- | :--- |
| Raw camera | `GET /api/stream/camera/feed` | Latest shared frame from the camera. |
| Detection overlay | `GET /api/stream/detection/feed` | Same shared frame with checkerboard targets and battery contours drawn on top. |

## Shared Capture

The camera adapter now uses one shared capture source.

That means the following can run at the same time against the same camera:

- raw stream
- detection stream
- `POST /api/path/detect`
- checkerboard visibility checks used by `GET /api/status`
- `POST /api/calibration`

The backend no longer opens a fresh `VideoCapture` per endpoint.

## Quick Start

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open the streams directly:

```bash
open http://localhost:8000/api/stream/camera/feed
open http://localhost:8000/api/stream/detection/feed
```

Or use the calibration page:

```bash
open docs/calibration-tester.html
```

## Browser Usage

```html
<img src="http://localhost:8000/api/stream/camera/feed" alt="Raw camera" />
<img src="http://localhost:8000/api/stream/detection/feed" alt="Detection stream" />
```

## Notes

- `GET /api/status` is the source of truth for checkerboard visibility and calibration progress.
- `POST /api/path/detect` returns the latest snapshot plus battery detections, but it no longer performs calibration.
- Runtime calibration is driven only by `POST /api/calibration`.
