from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class CalibrationSettings:
    """Detection settings mirrored from app/adapters/camera_vision.py defaults."""

    blur_kernel: int = 3
    canny_low: int = 50
    canny_high: int = 150
    dilate_kernel: int = 3
    dilate_iterations: int = 1
    area_min: int = 8000
    area_max: int = 150000
    approx_epsilon: float = 0.02
    vertices_min: int = 4
    vertices_max: int = 8
    aspect_min: float = 1.05
    aspect_max: float = 3.5
    max_mean_gray: int = 150


WINDOW_NAME = "NenaBot Detection Parameter Tuning"
TRACKBAR_WINDOW = "Detection Sliders"

DEFAULTS = CalibrationSettings()


def _nothing(_: int) -> None:
    return


def _odd(value: int) -> int:
    if value < 1:
        value = 1
    if value % 2 == 0:
        value += 1
    return value


def _create_trackbars() -> None:
    cv2.namedWindow(TRACKBAR_WINDOW, cv2.WINDOW_NORMAL)

    cv2.createTrackbar(
        "Blur kernel", TRACKBAR_WINDOW, DEFAULTS.blur_kernel, 31, _nothing
    )
    cv2.createTrackbar("Canny low", TRACKBAR_WINDOW, DEFAULTS.canny_low, 255, _nothing)
    cv2.createTrackbar(
        "Canny high", TRACKBAR_WINDOW, DEFAULTS.canny_high, 255, _nothing
    )
    cv2.createTrackbar(
        "Dilate kernel", TRACKBAR_WINDOW, DEFAULTS.dilate_kernel, 21, _nothing
    )
    cv2.createTrackbar(
        "Dilate iter", TRACKBAR_WINDOW, DEFAULTS.dilate_iterations, 10, _nothing
    )

    cv2.createTrackbar("Area min", TRACKBAR_WINDOW, DEFAULTS.area_min, 300000, _nothing)
    cv2.createTrackbar("Area max", TRACKBAR_WINDOW, DEFAULTS.area_max, 500000, _nothing)

    cv2.createTrackbar(
        "Approx eps x1000",
        TRACKBAR_WINDOW,
        int(DEFAULTS.approx_epsilon * 1000),
        100,
        _nothing,
    )
    cv2.createTrackbar(
        "Vertices min", TRACKBAR_WINDOW, DEFAULTS.vertices_min, 12, _nothing
    )
    cv2.createTrackbar(
        "Vertices max", TRACKBAR_WINDOW, DEFAULTS.vertices_max, 12, _nothing
    )

    cv2.createTrackbar(
        "Aspect min x100",
        TRACKBAR_WINDOW,
        int(DEFAULTS.aspect_min * 100),
        800,
        _nothing,
    )
    cv2.createTrackbar(
        "Aspect max x100",
        TRACKBAR_WINDOW,
        int(DEFAULTS.aspect_max * 100),
        800,
        _nothing,
    )
    cv2.createTrackbar(
        "Max mean gray", TRACKBAR_WINDOW, DEFAULTS.max_mean_gray, 255, _nothing
    )


def _read_settings() -> CalibrationSettings:
    blur_kernel = _odd(cv2.getTrackbarPos("Blur kernel", TRACKBAR_WINDOW))

    canny_low = cv2.getTrackbarPos("Canny low", TRACKBAR_WINDOW)
    canny_high = cv2.getTrackbarPos("Canny high", TRACKBAR_WINDOW)
    if canny_high <= canny_low:
        canny_high = min(255, canny_low + 1)

    dilate_kernel = max(1, cv2.getTrackbarPos("Dilate kernel", TRACKBAR_WINDOW))
    dilate_iterations = cv2.getTrackbarPos("Dilate iter", TRACKBAR_WINDOW)

    area_min = cv2.getTrackbarPos("Area min", TRACKBAR_WINDOW)
    area_max = cv2.getTrackbarPos("Area max", TRACKBAR_WINDOW)
    if area_max <= area_min:
        area_max = area_min + 1

    approx_eps = cv2.getTrackbarPos("Approx eps x1000", TRACKBAR_WINDOW) / 1000.0
    approx_eps = max(0.001, approx_eps)

    vertices_min = max(3, cv2.getTrackbarPos("Vertices min", TRACKBAR_WINDOW))
    vertices_max = max(3, cv2.getTrackbarPos("Vertices max", TRACKBAR_WINDOW))
    if vertices_max < vertices_min:
        vertices_max = vertices_min

    aspect_min = cv2.getTrackbarPos("Aspect min x100", TRACKBAR_WINDOW) / 100.0
    aspect_max = cv2.getTrackbarPos("Aspect max x100", TRACKBAR_WINDOW) / 100.0
    if aspect_max < aspect_min:
        aspect_max = aspect_min

    max_mean_gray = cv2.getTrackbarPos("Max mean gray", TRACKBAR_WINDOW)

    return CalibrationSettings(
        blur_kernel=blur_kernel,
        canny_low=canny_low,
        canny_high=canny_high,
        dilate_kernel=dilate_kernel,
        dilate_iterations=dilate_iterations,
        area_min=area_min,
        area_max=area_max,
        approx_epsilon=approx_eps,
        vertices_min=vertices_min,
        vertices_max=vertices_max,
        aspect_min=aspect_min,
        aspect_max=aspect_max,
        max_mean_gray=max_mean_gray,
    )


def detect_and_annotate(
    frame: np.ndarray, s: CalibrationSettings
) -> tuple[np.ndarray, np.ndarray, int]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    annotated = frame.copy()

    blurred = cv2.GaussianBlur(gray, (s.blur_kernel, s.blur_kernel), 0)
    edges = cv2.Canny(blurred, s.canny_low, s.canny_high)
    kernel = np.ones((s.dilate_kernel, s.dilate_kernel), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=s.dilate_iterations)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detected = 0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < s.area_min or area > s.area_max:
            continue

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, s.approx_epsilon * peri, True)
        if len(approx) < s.vertices_min or len(approx) > s.vertices_max:
            continue

        rect = cv2.minAreaRect(contour)
        width_px, height_px = rect[1]
        if width_px == 0 or height_px == 0:
            continue

        aspect = max(width_px, height_px) / min(width_px, height_px)
        if aspect < s.aspect_min or aspect > s.aspect_max:
            continue

        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, -1)
        if cv2.mean(gray, mask=mask)[0] > s.max_mean_gray:
            continue

        box = cv2.boxPoints(rect).astype(int)
        cv2.drawContours(annotated, [box], 0, (0, 255, 255), 2)
        center = tuple(map(int, rect[0]))
        cv2.drawMarker(annotated, center, (0, 255, 255), cv2.MARKER_CROSS, 12, 1)
        detected += 1

    cv2.putText(
        annotated,
        f"Detections: {detected}",
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
    )

    return annotated, edges, detected


def _display_frame(annotated: np.ndarray, edges: np.ndarray) -> None:
    edges_bgr = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    h = min(annotated.shape[0], edges_bgr.shape[0])
    a = cv2.resize(annotated, (int(annotated.shape[1] * h / annotated.shape[0]), h))
    e = cv2.resize(edges_bgr, (int(edges_bgr.shape[1] * h / edges_bgr.shape[0]), h))

    combined = np.hstack([a, e])
    cv2.imshow(WINDOW_NAME, combined)


def _print_settings(s: CalibrationSettings) -> None:
    print("\nCurrent settings:")
    print(f"blur_kernel={s.blur_kernel}")
    print(f"canny_low={s.canny_low}")
    print(f"canny_high={s.canny_high}")
    print(f"dilate_kernel={s.dilate_kernel}")
    print(f"dilate_iterations={s.dilate_iterations}")
    print(f"area_min={s.area_min}")
    print(f"area_max={s.area_max}")
    print(f"approx_epsilon={s.approx_epsilon:.3f}")
    print(f"vertices_min={s.vertices_min}")
    print(f"vertices_max={s.vertices_max}")
    print(f"aspect_min={s.aspect_min:.2f}")
    print(f"aspect_max={s.aspect_max:.2f}")
    print(f"max_mean_gray={s.max_mean_gray}")

    print(
        "\nPaste this into app/adapters/camera_vision.py (DETECTION_CALIBRATION_OVERRIDES):"
    )
    print("DETECTION_CALIBRATION_OVERRIDES = {")
    print(f'    "blur_kernel": {s.blur_kernel},')
    print(f'    "canny_low": {s.canny_low},')
    print(f'    "canny_high": {s.canny_high},')
    print(f'    "dilate_kernel": {s.dilate_kernel},')
    print(f'    "dilate_iterations": {s.dilate_iterations},')
    print(f'    "area_min": {s.area_min},')
    print(f'    "area_max": {s.area_max},')
    print(f'    "approx_epsilon": {s.approx_epsilon:.3f},')
    print(f'    "vertices_min": {s.vertices_min},')
    print(f'    "vertices_max": {s.vertices_max},')
    print(f'    "aspect_min": {s.aspect_min:.2f},')
    print(f'    "aspect_max": {s.aspect_max:.2f},')
    print(f'    "max_mean_gray": {s.max_mean_gray},')
    print("}")


def _choose_source(args: argparse.Namespace) -> tuple[str, str | None, int]:
    mode = args.source
    image = args.image
    camera_index = args.camera

    if mode is None:
        choice = (
            input("Choose source [c]amera / [i]mage (default: camera): ")
            .strip()
            .lower()
        )
        mode = "image" if choice.startswith("i") else "camera"

    if mode == "image" and image is None:
        image = input("Enter image path: ").strip()

    return mode, image, camera_index


def _run_image_mode(image_path: str) -> None:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    frame = cv2.imread(str(path))
    if frame is None:
        raise RuntimeError(f"Unable to read image: {path}")

    while True:
        settings = _read_settings()
        annotated, edges, _ = detect_and_annotate(frame, settings)
        _display_frame(annotated, edges)

        key = cv2.waitKey(15) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            _print_settings(settings)


def _run_camera_mode(camera_index: int) -> None:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open camera index {camera_index}")

    print("Camera mode controls: [q]=quit, [s]=print current settings")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            settings = _read_settings()
            annotated, edges, _ = detect_and_annotate(frame, settings)
            _display_frame(annotated, edges)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                _print_settings(settings)
    finally:
        cap.release()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive detection tuning for NenaBot battery contour detection"
    )
    parser.add_argument(
        "--source", choices=["camera", "image"], default=None, help="Input source mode"
    )
    parser.add_argument(
        "--image", default=None, help="Path to test image (required for image mode)"
    )
    parser.add_argument(
        "--camera", type=int, default=0, help="Camera index for camera mode"
    )
    args = parser.parse_args()

    mode, image_path, camera_index = _choose_source(args)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    _create_trackbars()

    print("\nCalibration controls:")
    print("- Move sliders in 'Detection Sliders' to tune contour detection")
    print("- Press 's' to print current values")
    print("- Press 'q' to quit")

    if mode == "image":
        if not image_path:
            raise ValueError("Image mode selected but no image path was provided")
        _run_image_mode(image_path)
    else:
        _run_camera_mode(camera_index)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
