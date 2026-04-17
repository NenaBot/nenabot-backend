# Frontend Integration

This document summarizes the current frontend-to-backend interaction model for calibration, path planning, job execution, and results browsing.

The frontend talks only to the FastAPI backend under the `/api` prefix.

## Runtime Calibration

Calibration is no longer part of `POST /api/path/detect`.

- The frontend reads calibration state from `GET /api/status`.
- The calibration tester drives the guided 4-point flow through `POST /api/calibration`.
- Live preview uses the shared raw and detection streams.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Calibration Tester
    participant BE as Backend API

    Note over FE,BE: Base URL http://localhost:8000, API prefix /api

    U->>FE: Open calibration page
    FE->>BE: GET /api/status
    BE-->>FE: calibration { intrinsicsLoaded, checkerboardVisible, currentStep, calibrated, lastCalibratedAt }

    opt Optional live previews
        FE->>BE: GET /api/stream/camera/feed
        BE-->>FE: raw MJPEG stream
        FE->>BE: GET /api/stream/detection/feed
        BE-->>FE: detection MJPEG stream
    end

    U->>FE: Click Start Calibration
    FE->>BE: POST /api/calibration { action: "start" }
    BE-->>FE: referenceImageBase64 + targetPoint + currentStep=0

    loop Touch 4 points
        U->>FE: Move arm to highlighted point and click Capture
        FE->>BE: POST /api/calibration { action: "capture" }
        alt step 1-3
            BE-->>FE: capturedPoints + next targetPoint + currentStep
        else final step
            BE-->>FE: calibrated=true + lastCalibratedAt
        end
    end

    FE->>BE: GET /api/status
    BE-->>FE: calibration ready
```

## Detection, Path Planning, And Job Execution

The job tester flow is separate from calibration.

- `POST /api/path/detect` returns only detections and the latest snapshot.
- `POST /api/path/populate` converts detection contours into perimeter measurement points.
- `POST /api/job` converts pixel points into robot waypoints and starts the job.
- `GET /api/job/{job_id}/events` is the realtime progress stream.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Job Tester
    participant BE as Backend API

    Note over FE,BE: Calibration must already be complete

    opt Optional live preview streams
        FE->>BE: GET /api/stream/camera/feed
        BE-->>FE: Camera stream
        FE->>BE: GET /api/stream/detection/feed
        BE-->>FE: Detection stream
    end

    FE->>BE: GET /api/status
    BE-->>FE: calibration state

    U->>FE: Click Detect
    FE->>BE: POST /api/path/detect { options: {} }
    BE-->>FE: { requestSucceeded, detections, image_base64, error, options }

    opt Populate perimeter measurement points
        U->>FE: Click Populate Path
        FE->>BE: POST /api/path/populate { batteries, measuringPointsPerCm }
        BE-->>FE: path { index, batteryNr, cornerIndex, measurementIndex, pixelX, pixelY }
    end

    U->>FE: Click Start Job
    FE->>BE: POST /api/job { path, workZ, workR, dryRun, imageBase64 }
    Note over BE: Validate calibration, waypoint reachability, and robot readiness
    BE-->>FE: job payload with id and stored path

    FE->>BE: GET /api/job/{job_id}/events
    BE-->>FE: job:snapshot
    BE-->>FE: job:started

    loop For each waypoint
        BE-->>FE: job:waypoint_started
        BE-->>FE: job:waypoint_completed + measurement
        FE->>FE: Update progress UI
    end

    alt Job ends
        BE-->>FE: job:completed
    else Job fails
        BE-->>FE: job:failed
    else Job stopped
        BE-->>FE: job:stopped
    end
```

## Results Flow

The results page is read-only and reconstructs the overlay client-side.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant FE as Job Results Page
    participant BE as Backend API

    U->>FE: Open results page
    FE->>BE: GET /api/job
    BE-->>FE: jobs list

    U->>FE: Select a job
    FE->>BE: GET /api/job/{job_id}
    BE-->>FE: job status + path + measurements
    FE->>BE: GET /api/job/{job_id}/image
    BE-->>FE: image/jpeg
    FE->>FE: Render base image and measurement overlays
```

## Endpoint Summary

- `GET /api/status`
- `POST /api/calibration`
- `GET /api/stream/camera/feed`
- `GET /api/stream/detection/feed`
- `POST /api/path/detect`
- `POST /api/path/populate`
- `POST /api/job`
- `GET /api/job/{job_id}/events`
- `GET /api/job`
- `GET /api/job/{job_id}`
- `GET /api/job/{job_id}/image`
