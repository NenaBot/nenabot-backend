# Robot Arm Sampling System: Calibration Guide

This document outlines the standard operating procedure to recalibrate the camera and the robot arm mapping matrix. Calibration is necessary if the position(distance) of the camera and the robotarm is changed. Related files are located in folder `calibration-coordinate-mapping`.

## Prerequisites & Physical Setup

* **Hardware:**
    * The robotic arm and camera fully mounted in their operational positions.
    * An A3-sized printed calibration chessboard. The pattern **must** have 9x7 squares (which results in 8x6 inner intersections). The file of checkerboard pattern used is included in folder `docs` (`checkerboard-picture.pdf`).

* **Software Environment:**
    * Raspberry Pi running Linux.
    * Python environment with `opencv-python` and `numpy` installed.
    * `v4l-utils` installed for camera hardware control (`sudo apt install v4l-utils`).

---
> **Note:** Currently, the focus of the camera is fixed to 35 in the environment. So step 1 and step 2 is only needed when camera's focus is changed. Step 4 is nesscessary when the distance between the camera and the robot arm changes

## Step 1: Lock Camera Focus (Linux Setup)

Because the system operates on a Raspberry Pi (Linux), Windows-specific scripts like `camera_focus.py` (which rely on DirectShow) are not used. Instead, we lock the camera's focus to the environment directly via the Linux terminal.

1.  Open a terminal on the Raspberry Pi.
2.  Find your camera's device path by running:
    ```bash
    v4l2-ctl --list-devices
    ```
    *(Note the device path, typically `/dev/video0`)*
3.  Disable autofocus and lock the absolute focus to 35:
    ```bash
    v4l2-ctl -d /dev/video0 --set-ctrl=focus_auto=0
    v4l2-ctl -d /dev/video0 --set-ctrl=focus_absolute=35
    ```

> **Developer Note for Linux Migration:** > Before proceeding with the Python scripts below, you must update the video capture backend in your code. Open `take_picture.py`, `compare_distortions.py`, and `dobot_vision_control.py`. Change instances of `cv2.VideoCapture(0, cv2.CAP_DSHOW)` to `cv2.VideoCapture(0)`. DirectShow (`CAP_DSHOW`) will crash on Linux.

---

## Step 2: Intrinsic Calibration (Capturing Lens Distortion)

This step captures the physical curvature of the camera lens so the software can mathematically flatten the "fisheye" distortion.

1.  Lay the A3 chessboard completely flat within the camera's field of view.
2.  Run the capture script:
    ```bash
    python3 take_picture.py
    ```
3.  A video feed will appear. When the system successfully detects the chessboard, lines will be drawn connecting the corners, and "READY TO SAVE" will appear on the screen.
4.  Press `s` on your keyboard to save the frame. 
5.  Move the chessboard to different angles, heights, and edges of the camera view, pressing `s` to capture **at least 15-20 different images**.
6.  Press `q` to quit. The RAW images will be saved in the `calibration_images` folder.
7.  **Run your intrinsic calculation script** (e.g., `intrinsic-calibration.py`) to process the images in the folder. This will output the `camera_params.json` file.

---

## Step 3 (optional): Verify Distortion Correction

Before mapping coordinates to the robot, verify that the intrinsic calibration successfully flattens the image.

1.  Run the comparison script:
    ```bash
    python3 compare_distortions.py
    ```
2.  A preview window will open showing the RAW camera feed next to the UNDISTORTED feed. 
3.  Look at straight lines in the real world (e.g., the edge of a table, a ruler, or the chessboard lines). In the UNDISTORTED view, these lines should be perfectly straight.
4.  If desired, press `s` to save a side-by-side comparison image.
5.  Press `q` to exit.

---

## Step 4: Extrinsic Calibration (Robot Mapping)

This step maps the 2D flattened camera pixels to the 3D physical workspace of the Dobot arm.

> **Developer Note for Linux Migration:** > Open `robot_touch.py` and `dobot_vision_control.py`. Update the serial port connection string from `"COM5"` (Windows) to the correct Linux serial port, which is usually `"/dev/ttyUSB0"`.

1.  Place the chessboard flat in the exact working area where battery samples will be placed during normal operation. **Do not move the chessboard after this point.**
2.  Run the touch collection script:
    ```bash
    python3 robot_touch.py
    ```
3.  Follow the terminal prompts carefully:
    * Press the physical UNLOCK button on the Dobot arm.
    * Manually guide the tip of the robot arm to the specific grid intersections on the chessboard requested by the script.
    * Come back to the keyboard and press `[ENTER]` to record the exact `X, Y, Z` coordinates.
4.  Repeat this process for the 4 points requested by the script.
5.  Copy the final JSON data block printed in the terminal.
6.  Paste this data into your `mapping-matrix.py` script and run it to generate the `robot_mapping.json` file.

---

## Step 5: Final System Validation

Finally, verify the end-to-end accuracy of the vision system interacting with the robot arm.

1.  Run the vision control test:
    ```bash
    python3 dobot_vision_control.py
    ```
2.  **Stand Clear:** The arm will perform an automatic homing sequence. It takes about 15 seconds.
3.  Once the camera feed appears, place a test object (or an empty piece of paper) in the work area.
4.  Click on a specific point in the video feed.
5.  The robotic arm should move exactly to the physical point you clicked on the screen. By default, it will hover at a safe Z-height of `-48.0` to avoid crashing into the table.
6.  **Fine-Tuning:** If the arm consistently misses the target by a few millimeters, open `dobot_vision_control.py` and adjust the `X_OFFSET` and `Y_OFFSET` variables at the top of the file until it is perfectly accurate.