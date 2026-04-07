# Detection Parameter Tuning

This guide documents how to tweak battery contour-detection thresholds without changing detection logic.

The tunable values live in app/adapters/camera_vision.py in:

- DetectionCalibration (defaults)
- DETECTION_CALIBRATION_OVERRIDES (copy-paste overrides)

Aruco marker tuning is intentionally excluded here because marker-based detection is deprecated in this project.

## Quick Workflow

1. Run the interactive tuning tool.
2. Tune sliders while viewing detection overlays.
3. Press s to print a copy-paste override block.
4. Paste that block into DETECTION_CALIBRATION_OVERRIDES.
5. Restart backend and verify with /api/path/detect and /api/stream/detection/feed.

## Run the Tool

From repository root:

```bash
python docs/detection_parameter_tuning.py
```

Use camera source:

```bash
python docs/detection_parameter_tuning.py --source camera --camera 0
```

Use a static image for repeatable tuning:

```bash
python docs/detection_parameter_tuning.py --source image --image data/images/capture_example.jpg
```

## Copy-Paste Example

Paste into app/adapters/camera_vision.py:

```python
DETECTION_CALIBRATION_OVERRIDES = {
    "blur_kernel": 3,
    "canny_low": 60,
    "canny_high": 170,
    "dilate_kernel": 3,
    "dilate_iterations": 1,
    "area_min": 9000,
    "area_max": 140000,
    "approx_epsilon": 0.020,
    "vertices_min": 4,
    "vertices_max": 8,
    "aspect_min": 1.10,
    "aspect_max": 3.20,
    "max_mean_gray": 145,
}
```

## Parameter Effects

- blur_kernel: Higher values smooth noise more but can erase small edges.
- canny_low / canny_high: Higher values require stronger edges to detect contours.
- dilate_kernel / dilate_iterations: Expands edge pixels to close small gaps.
- area_min / area_max: Rejects too-small noise and too-large non-battery regions.
- approx_epsilon: Larger values simplify contour shape more aggressively.
- vertices_min / vertices_max: Constrains accepted contour polygon complexity.
- aspect_min / aspect_max: Filters by bounding-rectangle aspect ratio.
- max_mean_gray: Rejects bright regions that are likely reflections/background.

## Suggested Presets

Low-light / noisy background:

```python
DETECTION_CALIBRATION_OVERRIDES = {
    "blur_kernel": 5,
    "canny_low": 40,
    "canny_high": 130,
    "dilate_kernel": 3,
    "dilate_iterations": 2,
    "area_min": 10000,
    "area_max": 150000,
    "approx_epsilon": 0.018,
    "vertices_min": 4,
    "vertices_max": 9,
    "aspect_min": 1.00,
    "aspect_max": 3.60,
    "max_mean_gray": 165,
}
```

Strict / fewer false positives:

```python
DETECTION_CALIBRATION_OVERRIDES = {
    "blur_kernel": 3,
    "canny_low": 70,
    "canny_high": 190,
    "dilate_kernel": 3,
    "dilate_iterations": 1,
    "area_min": 12000,
    "area_max": 120000,
    "approx_epsilon": 0.022,
    "vertices_min": 4,
    "vertices_max": 7,
    "aspect_min": 1.15,
    "aspect_max": 2.80,
    "max_mean_gray": 135,
}
```

## Notes

- Keep blur_kernel odd; even values are auto-corrected.
- Keep canny_high > canny_low; invalid values are auto-corrected.
- Keep area_max > area_min; invalid values are auto-corrected.
- After changing overrides, restart backend to apply settings.
