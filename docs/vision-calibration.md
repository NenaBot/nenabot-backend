# Vision Calibration

Nenabot now uses a two-part calibration model:

1. A precomputed intrinsic camera profile JSON.
2. A runtime 4-point robot mapping JSON.

## Files

| File | Purpose |
| :--- | :------ |
| `calibration-coordinate-mapping/camera_params.json` | Default intrinsic camera profile loaded at startup unless `NENABOT_INTRINSICS_PATH` is set. |
| `data/calibration/robot_mapping.json` | Runtime 4-point robot mapping written by `POST /api/calibration`. This file is overwritten on successful recalibration. |

## Intrinsics

Intrinsics are camera-specific and are expected to be created offline.

The backend loads:

- `camera_matrix`
- `dist_coeff`
- `resolution`
- optional checkerboard metadata

The live runtime calibration must use the same camera resolution as the intrinsic file. The backend now adopts the intrinsic file resolution automatically so the highlighted checkerboard points match the research calibration setup.

If the intrinsic JSON is missing or invalid:

- `GET /api/status` reports `intrinsicsLoaded = false`
- runtime calibration cannot complete
- job creation remains blocked

## Runtime 4-Point Calibration

Open [`docs/calibration-tester.html`](./calibration-tester.html) and follow the guided flow:

1. Ensure the checkerboard is visible in the camera.
2. Move the robot to the desired start pose.
3. Press **Start Calibration**.
4. The backend captures the current frame, detects the checkerboard, stores the start pose, and returns the first target point.
5. Move the robot tip to the highlighted point and press **Capture Current Point**.
6. Repeat until all 4 points are captured.
7. After the 4th point, the backend solves the mapping and overwrites `data/calibration/robot_mapping.json`.

The fixed checkerboard sequence is:

- `P1 (1, 0)`
- `P2 (1, 6)`
- `P3 (5, 7)`
- `P4 (5, 0)`

Those are the same four board indices used in the research scripts. The detection overlay also draws the `row+` and `col+` directions from `P1` so the operator can confirm the board orientation before capturing points.

## Mapping File Contents

`robot_mapping.json` stores:

- `calibrated_at`
- `intrinsics_path`
- `resolution`
- `checkerboard`
- `image_points`
- `robot_points`
- `start_pose`
- `rvec`
- `tvec`
- `plane`

`calibrated_at` is surfaced through `GET /api/status` as `lastCalibratedAt` so the frontend can show when calibration was last completed.

## Status API

`GET /api/status` returns:

- `intrinsicsLoaded`
- `checkerboardVisible`
- `calibrationInProgress`
- `currentStep`
- `totalSteps`
- `calibrated`
- `lastCalibratedAt`

This is the only status endpoint the calibration UI needs.
