# Vision Calibration Tool

This project now includes an interactive calibration script to tune the battery detection thresholds from `app/adapters/camera_vision.py`.

## Run

From the project root:

```bash
python "docs/machine vision/vision_calibration.py"
```

Optional arguments:

```bash
python "docs/machine vision/vision_calibration.py" --source camera --camera 0
python "docs/machine vision/vision_calibration.py" --source image --image data/images/sample.jpg
```

## What It Does

- Starts with source selection: camera or test image.
- Uses OpenCV trackbars to tune detection parameters in real time.
- Shows a live preview window with:
    - Left: annotated detections
    - Right: edge map used by contour detection
- Keeps initial slider defaults equal to current hard-coded values in `camera_vision.py`.

## Controls

- `q`: quit
- `s`: print current settings to terminal

Use the printed values to update the detection constants in `app/adapters/camera_vision.py` after calibration.
