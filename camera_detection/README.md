# Object size measurement with ArUco (OpenCV + Python)

Measure Samsung lithium battery cell dimensions in millimeters using an ArUco marker as a scale reference.

## Overview

This project detects and measures Samsung lithium battery cells using computer vision. The system:

- Uses an ArUco marker for scale calibration
- Detects rectangular objects with dark labels (battery stickers)
- Filters out non-battery objects based on shape, size, and color
- Displays real-time measurements in millimeters

## What you need

- A printed ArUco marker (DICT_4X4_50, ID 0)
- A webcam
- Good lighting and a flat surface
- Samsung batteries to measure

## Install

1. Create a virtual environment

```bash
python -m venv .venv
```

2. Activate virtual environment

**Bash / Shell (Linux, macOS):**

```bash
source .venv/bin/activate
```

**PowerShell (Windows):**

```powershell
.venv\Scripts\Activate.ps1
```

**Command Prompt (Windows):**

```cmd
.venv\Scripts\activate.bat
```

3. Install the required dependencies:

```
pip install -r requirements.txt
```

### Using external camera

By default, this application uses camera `0` if no camera is specified.
To select a different camera, run the program for example with:

```bash
python main.py --camera 1
```

For **Windows** you can disable unnecessary cameras:

1. Open **Device Manager**
2. Expand **Cameras**
3. For each camera you do **not** want to use:
   - Right-click the device
   - Select **Disable device**
4. Leave only the desired external camera enabled
5. Restart the application

Remember to re-enable disabled cameras later if you need them.

## Run

```bash
python main.py
```

The marker size defaults to 48mm. If your printed marker is different, specify it:

```bash
python main.py --marker-size <your_size_in_mm>
```

## How it works

### Detection pipeline

1. **ArUco marker detection** - Establishes scale (pixels per mm)
2. **Edge detection** - Canny edge detection with light morphology
3. **Contour filtering** - Multiple filters to identify batteries:
   - Area: 8,000 - 150,000 pixels
   - Shape: 4-8 sided polygons (rectangular)
   - Aspect ratio: 1.05:1 to 3.5:1
   - Dark region check: Mean intensity < 150 (detects black sticker)
4. **Measurement** - Rotated bounding box dimensions converted to mm

### Battery-specific filtering

- Targets rectangular shapes with black labels (Samsung branding)
- Filters out white/light background objects
- Handles various battery sizes and orientations
- Aspect ratio range accommodates both square and elongated cells

## Development notes

### Iterations tried today

1. **Initial approach**: Basic threshold + contour detection → too sensitive, detected everything
2. **Color filtering**: HSV gray metallic edge detection → didn't work reliably
3. **Black label detection**: Threshold for dark stickers only → measured sticker, not full battery
4. **Edge-based full battery**: Heavy morphology to connect edges → merged batteries together
5. **Current approach**: Light edge detection + polygon approximation + intensity check → works well

### Known limitations

- Requires good lighting for edge detection
- Batteries must be close enought to the camera
- Batteries must be on same plane as marker
- May detect ghost shapes in complex backgrounds
- Best results with marker and batteries clearly visible

### Future improvements

**Trained YOLO model** - The current edge-based detection with filtering works well but still occasionally detects ghost shapes on complex backgrounds. Training a YOLOv8 object detection model specifically on Samsung battery images would eliminate these false positives by learning the actual appearance of batteries (shape, text, branding) rather than relying on geometric heuristics. This would require:

- Collecting 200-500 images of Samsung batteries in various orientations
- Annotating battery locations using tools like LabelImg or Roboflow
- Training YOLOv8 on the dataset (~1-2 hours on GPU)
- Replacing the edge detection pipeline with YOLO inference
- Expected outcome: near-zero false positives and more robust detection in varied lighting

## Measurements

The printed markers in this project measure **48 mm** on the outer black square side. Use `--marker-size 48` when running.

## Generate markers

Use the included script to generate printable ArUco markers:

```bash
python generate_marker.py --dict DICT_4X4_50 --id 0 --size 800 --output marker.png
```

- [ ] check for the focus issue on the camera if you have trouble detecting the marker or batteries. Adjust the distance and lighting for best results.
