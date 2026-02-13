from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Tuple


@dataclass
class CaptureResult:
    ok: bool
    image_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PoseEstimate:
    ok: bool
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    r: float = 0.0
    confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class Corner:
    x: float
    y: float


@dataclass
class DetectionResult:
    corners: List[Corner] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    confidence: float = 0.0


@dataclass
class DetectionResults:
    ok: bool
    detections: List[DetectionResult] = field(default_factory=list)
    image_base64: Optional[str] = None
    error: Optional[str] = None


class CameraVisionAdapter:
    """
    Merged camera + vision adapter.

    Handles:
    - Single-frame capture and save to disk
    - ArUco marker-based detection with battery corner extraction
    - MJPEG streaming (raw camera feed or detection-overlay feed)
    """

    def __init__(
        self,
        device_index: int = 0,
        output_dir: str = "data/images",
        marker_size_mm: float = 48.0,
        frame_width: int = 1280,
        frame_height: int = 720,
    ) -> None:
        self._device_index = device_index
        self._output_dir = Path(output_dir)
        self._marker_size_mm = marker_size_mm
        self._frame_width = frame_width
        self._frame_height = frame_height

        # Streaming state
        self._camera_streaming = False
        self._detection_streaming = False

    # ---- single-frame capture ----

    def capture(self) -> CaptureResult:
        try:
            import cv2
        except Exception as exc:  # pragma: no cover
            return CaptureResult(False, error=f"OpenCV not available: {exc}")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(self._device_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)
        if not cap.isOpened():
            return CaptureResult(False, error="Unable to open camera")

        # Discard initial frames so the sensor can adjust exposure/white-balance
        for _ in range(10):
            cap.read()

        ok, frame = cap.read()
        cap.release()
        if not ok:
            return CaptureResult(False, error="Failed to read frame")

        filename = f"capture_{datetime.utcnow().isoformat().replace(':', '-')}.jpg"
        path = self._output_dir / filename
        cv2.imwrite(str(path), frame)
        return CaptureResult(True, image_path=str(path))

    # ---- detection (battery corners) ----

    def detect(self, image_path: str) -> DetectionResults:
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # pragma: no cover
            return DetectionResults(False, error=f"OpenCV not available: {exc}")

        image = cv2.imread(image_path)
        if image is None:
            return DetectionResults(False, error="Unable to read image")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # --- ArUco marker for scale ---
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
        marker_corners, ids, _ = detector.detectMarkers(gray)

        pixels_per_mm: Optional[float] = None
        if ids is not None and len(marker_corners) > 0:
            side_px = float(np.linalg.norm(marker_corners[0][0][0] - marker_corners[0][0][1]))
            pixels_per_mm = side_px / self._marker_size_mm

        # --- battery contour detection ---
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: List[DetectionResult] = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 8000 or area > 150000:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) < 4 or len(approx) > 8:
                continue
            rect = cv2.minAreaRect(contour)
            w, h = rect[1]
            if w == 0 or h == 0:
                continue
            aspect = max(w, h) / min(w, h)
            if aspect < 1.05 or aspect > 3.5:
                continue
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            if cv2.mean(gray, mask=mask)[0] > 150:
                continue

            box = cv2.boxPoints(rect)
            corners = [Corner(x=float(pt[0]), y=float(pt[1])) for pt in box]
            center_x, center_y = float(rect[0][0]), float(rect[0][1])
            width_mm = float(w / pixels_per_mm) if pixels_per_mm else float(w)
            height_mm = float(h / pixels_per_mm) if pixels_per_mm else float(h)

            detections.append(DetectionResult(
                corners=corners,
                width_mm=width_mm,
                height_mm=height_mm,
                center_x=center_x,
                center_y=center_y,
                confidence=0.7 if pixels_per_mm else 0.3,
            ))

        if not detections:
            return DetectionResults(ok=False, error="No battery contour detected")

        return DetectionResults(ok=True, detections=detections)

    def detect_live(self, frame):
        """Run detection on a cv2 frame (numpy array), return annotated frame + result."""
        import cv2
        import numpy as np

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        annotated = frame.copy()

        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
        marker_corners, ids, _ = detector.detectMarkers(gray)

        pixels_per_mm = None
        if ids is not None and len(marker_corners) > 0:
            cv2.aruco.drawDetectedMarkers(annotated, marker_corners, ids)
            side_px = float(np.linalg.norm(marker_corners[0][0][0] - marker_corners[0][0][1]))
            pixels_per_mm = side_px / self._marker_size_mm

        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 8000 or area > 150000:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) < 4 or len(approx) > 8:
                continue
            rect = cv2.minAreaRect(contour)
            w, h = rect[1]
            if w == 0 or h == 0:
                continue
            aspect = max(w, h) / min(w, h)
            if aspect < 1.05 or aspect > 3.5:
                continue
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            if cv2.mean(gray, mask=mask)[0] > 150:
                continue

            box = cv2.boxPoints(rect).astype(int)
            cv2.drawContours(annotated, [box], 0, (0, 255, 255), 2)
            if pixels_per_mm:
                label = f"{w / pixels_per_mm:.1f}x{h / pixels_per_mm:.1f} mm"
                center = tuple(map(int, rect[0]))
                cv2.putText(annotated, label, (center[0] - 50, center[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        return annotated

    # ---- MJPEG streaming generators ----

    async def stream_camera(self) -> AsyncGenerator[bytes, None]:
        """Yield raw MJPEG frames from the camera."""
        import cv2

        self._camera_streaming = True
        cap = cv2.VideoCapture(self._device_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)

        try:
            while self._camera_streaming:
                ok, frame = cap.read()
                if not ok:
                    await asyncio.sleep(0.05)
                    continue
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                )
                await asyncio.sleep(0.033)  # ~30 fps
        finally:
            cap.release()
            self._camera_streaming = False

    async def stream_detection(self) -> AsyncGenerator[bytes, None]:
        """Yield MJPEG frames with detection overlay."""
        import cv2

        self._detection_streaming = True
        cap = cv2.VideoCapture(self._device_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)

        try:
            while self._detection_streaming:
                ok, frame = cap.read()
                if not ok:
                    await asyncio.sleep(0.05)
                    continue
                annotated = self.detect_live(frame)
                _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                )
                await asyncio.sleep(0.033)
        finally:
            cap.release()
            self._detection_streaming = False

    def stop_camera_stream(self) -> None:
        self._camera_streaming = False

    def stop_detection_stream(self) -> None:
        self._detection_streaming = False
