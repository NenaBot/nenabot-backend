from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    ok: bool
    image_path: str | None = None
    error: str | None = None


@dataclass
class PoseEstimate:
    ok: bool
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    r: float = 0.0
    confidence: float = 0.0
    error: str | None = None


@dataclass
class Corner:
    x: float
    y: float


@dataclass
class DetectionResult:
    corners: list[Corner] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    confidence: float = 0.0


@dataclass
class MarkerCorners:
    """Four pixel-corners of a single ArUco marker."""

    corners: list[Corner] = field(default_factory=list)


@dataclass
class DetectionResults:
    ok: bool
    detections: list[DetectionResult] = field(default_factory=list)
    image_base64: str | None = None
    pixels_per_mm: float | None = None
    marker_count: int = 0
    marker_corners: list[MarkerCorners] = field(default_factory=list)
    error: str | None = None


class CameraVisionAdapter:
    """Camera + vision adapter with lens distortion correction.

    Key design choices:
    - Single shared VideoCapture (Linux only allows one open handle per device)
    - Autofocus disabled, focus fixed at 35 for repeatable calibration
    - Lens distortion corrected via precomputed remap tables
    """

    def __init__(
        self,
        device_index: int = 0,
        output_dir: str = "data/images",
        marker_size_mm: float = 48.0,
        calibration_path: str = "CameraCalibration/camera-calibration.json",
        frame_width: int = 1920,
        frame_height: int = 1080,
    ) -> None:
        self._device_index = device_index
        self._output_dir = Path(output_dir)
        self._marker_size_mm = marker_size_mm
        self._frame_width = frame_width
        self._frame_height = frame_height

        # Single shared camera — never open more than one VideoCapture
        self._cap = None
        self._cap_lock = threading.Lock()
        self._camera_streaming = False
        self._detection_streaming = False

        # Calibration state (populated by _load_calibration)
        self._camera_matrix = None
        self._dist_coeffs = None
        self._undistort_maps: tuple | None = None
        self._load_calibration(calibration_path)

    # ------------------------------------------------------------------ #
    #  Calibration & undistortion                                         #
    # ------------------------------------------------------------------ #

    def _load_calibration(self, path: str) -> None:
        """Load camera matrix and distortion coefficients from a JSON file."""
        cal_path = Path(path)
        if not cal_path.exists():
            logger.warning(
                "Calibration file not found: %s — running without undistortion",
                cal_path,
            )
            return
        try:
            import numpy as np

            with open(cal_path) as f:
                cal = json.load(f)
            self._camera_matrix = np.array(cal["camera_matrix"], dtype=np.float64)
            self._dist_coeffs = np.array(cal["dist_coeff"], dtype=np.float64)
            res = cal.get("resolution")
            if res:
                self._frame_width, self._frame_height = int(res[0]), int(res[1])
            logger.info(
                "Loaded camera calibration from %s (%.4f reprojection error)",
                cal_path,
                cal.get("reprojection_error", -1),
            )
        except Exception as exc:
            logger.warning("Failed to load calibration: %s", exc)

    def _undistort(self, frame: np.ndarray) -> np.ndarray:
        """Remove lens distortion using precomputed remap tables (fast)."""
        if self._camera_matrix is None:
            return frame
        import cv2

        # Build remap tables once, reuse on every frame
        if self._undistort_maps is None:
            h, w = frame.shape[:2]
            new_mtx, _ = cv2.getOptimalNewCameraMatrix(
                self._camera_matrix,
                self._dist_coeffs,
                (w, h),
                0,
                (w, h),
            )
            map1, map2 = cv2.initUndistortRectifyMap(
                self._camera_matrix,
                self._dist_coeffs,
                None,
                new_mtx,
                (w, h),
                cv2.CV_16SC2,
            )
            self._undistort_maps = (map1, map2)

        return cv2.remap(
            frame, self._undistort_maps[0], self._undistort_maps[1], cv2.INTER_LINEAR
        )

    # ------------------------------------------------------------------ #
    #  Shared camera management                                           #
    # ------------------------------------------------------------------ #

    def _open_camera(self) -> bool:
        """Open the camera if not already open. Caller must hold _cap_lock."""
        import cv2

        if self._cap is not None and self._cap.isOpened():
            return True

        self._cap = cv2.VideoCapture(self._device_index)
        if not self._cap.isOpened():
            self._cap = None
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)
        self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  # disable autofocus
        self._cap.set(cv2.CAP_PROP_FOCUS, 35)  # fixed focus matching calibration
        return True

    def _read_frame(self) -> tuple[bool, "np.ndarray | None"]:
        """Read a single frame from the shared camera and undistort it."""
        with self._cap_lock:
            if not self._open_camera():
                return False, None
            ok, frame = self._cap.read()
        if ok:
            frame = self._undistort(frame)
        return ok, frame

    def release_camera(self) -> None:
        """Release the camera device."""
        with self._cap_lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            self._camera_streaming = False
            self._detection_streaming = False

    # ------------------------------------------------------------------ #
    #  Health check                                                       #
    # ------------------------------------------------------------------ #

    def ping(self) -> CaptureResult:
        """Lightweight check: can we open the camera device?"""
        try:
            import cv2  # noqa: F401
        except Exception as exc:  # pragma: no cover
            return CaptureResult(False, error=f"OpenCV not available: {exc}")
        with self._cap_lock:
            if not self._open_camera():
                return CaptureResult(False, error="Unable to open camera")
        return CaptureResult(True)

    # ------------------------------------------------------------------ #
    #  Single-frame capture                                               #
    # ------------------------------------------------------------------ #

    def capture(self) -> CaptureResult:
        """Capture a single undistorted frame and save to disk."""
        try:
            import cv2
        except Exception as exc:  # pragma: no cover
            return CaptureResult(False, error=f"OpenCV not available: {exc}")

        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Warm-up: discard frames so sensor adjusts exposure/white-balance
        if not self._camera_streaming:
            for _ in range(10):
                self._read_frame()

        ok, frame = self._read_frame()
        if not ok or frame is None:
            return CaptureResult(False, error="Failed to read frame")

        filename = f"capture_{datetime.utcnow().isoformat().replace(':', '-')}.jpg"
        path = self._output_dir / filename
        cv2.imwrite(str(path), frame)
        return CaptureResult(True, image_path=str(path))

    # ------------------------------------------------------------------ #
    #  Detection (battery corners via ArUco + contour)                    #
    # ------------------------------------------------------------------ #

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

        pixels_per_mm: float | None = None
        aruco_corners_out: list[MarkerCorners] = []
        if ids is not None and len(marker_corners) > 0:
            first_corner = marker_corners[0][0]
            side_px = float(np.linalg.norm(first_corner[0] - first_corner[1]))
            pixels_per_mm = side_px / self._marker_size_mm
            for mc in marker_corners:
                aruco_corners_out.append(
                    MarkerCorners(
                        corners=[
                            Corner(x=float(pt[0]), y=float(pt[1])) for pt in mc[0]
                        ],
                    )
                )

        # --- battery contour detection ---
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        detections: list[DetectionResult] = []

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

            detections.append(
                DetectionResult(
                    corners=corners,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    center_x=center_x,
                    center_y=center_y,
                    confidence=0.7 if pixels_per_mm else 0.3,
                )
            )

        if not detections:
            return DetectionResults(
                ok=False,
                error="No battery contour detected",
                pixels_per_mm=pixels_per_mm,
                marker_count=int(len(ids)) if ids is not None else 0,
                marker_corners=aruco_corners_out,
            )

        return DetectionResults(
            ok=True,
            detections=detections,
            pixels_per_mm=pixels_per_mm,
            marker_count=int(len(ids)) if ids is not None else 0,
            marker_corners=aruco_corners_out,
        )

    def detect_live(self, frame: np.ndarray) -> np.ndarray:
        """Run detection on a cv2 frame, return annotated frame."""
        import cv2
        import numpy as np

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        annotated = frame.copy()

        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
        marker_corners, ids, _ = detector.detectMarkers(gray)

        pixels_per_mm = None
        if ids is not None and len(marker_corners) > 0:
            cv2.aruco.drawDetectedMarkers(
                annotated,
                marker_corners,
                ids,
            )
            first_corner = marker_corners[0][0]
            side_px = float(np.linalg.norm(first_corner[0] - first_corner[1]))
            pixels_per_mm = side_px / self._marker_size_mm

        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blurred, 50, 150)
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

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
                cv2.putText(
                    annotated,
                    label,
                    (center[0] - 50, center[1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    2,
                )

        return annotated

    # ------------------------------------------------------------------ #
    #  MJPEG streaming                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _mjpeg_frame(jpeg_bytes: bytes) -> bytes:
        """Wrap JPEG bytes in an MJPEG boundary."""
        return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"

    def _error_frame(self, text: str) -> bytes:
        """Create a JPEG showing an error message (black background, red text)."""
        import cv2
        import numpy as np

        frame = np.zeros((self._frame_height, self._frame_width, 3), dtype=np.uint8)
        lines = text.split("\n")
        y0 = self._frame_height // 2 - 20 * (len(lines) - 1) // 2
        for i, line in enumerate(lines):
            cv2.putText(
                frame,
                line,
                (40, y0 + i * 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (80, 80, 255),
                2,
            )
        _, jpeg = cv2.imencode(".jpg", frame)
        return jpeg.tobytes()

    async def stream_camera(self) -> AsyncGenerator[bytes, None]:
        """Yield raw undistorted MJPEG frames from the shared camera."""
        import cv2

        if self._camera_streaming:
            yield self._mjpeg_frame(self._error_frame("Camera stream already active"))
            return

        self._camera_streaming = True
        with self._cap_lock:
            if not self._open_camera():
                self._camera_streaming = False
                yield self._mjpeg_frame(
                    self._error_frame(
                        "Camera not available\n(check device or opencv-python)"
                    ),
                )
                return

        loop = asyncio.get_running_loop()
        try:
            while self._camera_streaming:
                ok, frame = await loop.run_in_executor(None, self._read_frame)
                if not ok:
                    await asyncio.sleep(0.05)
                    continue
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                yield self._mjpeg_frame(jpeg.tobytes())
                await asyncio.sleep(0.033)  # ~30 fps
        finally:
            self._camera_streaming = False

    async def stream_detection(self) -> AsyncGenerator[bytes, None]:
        """Yield undistorted MJPEG frames with detection overlay from the shared camera."""
        import cv2

        if self._detection_streaming:
            yield self._mjpeg_frame(
                self._error_frame("Detection stream already active")
            )
            return

        self._detection_streaming = True
        with self._cap_lock:
            if not self._open_camera():
                self._detection_streaming = False
                yield self._mjpeg_frame(
                    self._error_frame(
                        "Camera not available\n(check device or opencv-python)"
                    ),
                )
                return

        loop = asyncio.get_running_loop()
        try:
            while self._detection_streaming:
                ok, frame = await loop.run_in_executor(None, self._read_frame)
                if not ok:
                    await asyncio.sleep(0.05)
                    continue
                annotated = await loop.run_in_executor(None, self.detect_live, frame)
                _, jpeg = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70]
                )
                yield self._mjpeg_frame(jpeg.tobytes())
                await asyncio.sleep(0.033)
        finally:
            self._detection_streaming = False

    def stop_camera_stream(self) -> None:
        self._camera_streaming = False

    def stop_detection_stream(self) -> None:
        self._detection_streaming = False

    # ------------------------------------------------------------------ #
    #  Overlay rendering                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def render_overlay(
        jpeg_bytes: bytes,
        detections: list,
        measurements: list | None = None,
        starting_point: tuple | None = None,
    ) -> bytes:
        """Draw detection boxes, measurement points, and start marker.

        Parameters
        ----------
        jpeg_bytes :
            Raw JPEG bytes of the base image.
        detections :
            List of DetectionResult (corners, center, sizes).
        measurements :
            List of Measurement dataclass instances (optional).
        starting_point :
            (x, y) pixel coordinates of the robot start (optional).

        Returns
        -------
        bytes
            JPEG bytes of the annotated image.

        """
        import cv2
        import numpy as np

        buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            return jpeg_bytes  # can't decode → return original

        # --- detection bounding boxes (cyan) ---
        first_target: tuple | None = None
        for det in detections:
            corners = det.corners if hasattr(det, "corners") else []
            if len(corners) >= 4:
                pts = np.array([[int(c.x), int(c.y)] for c in corners], dtype=np.int32)
                cv2.drawContours(frame, [pts], 0, (0, 255, 255), 2)
            # center cross
            cx, cy = int(det.center_x), int(det.center_y)
            cv2.drawMarker(
                frame,
                (cx, cy),
                (0, 255, 255),
                cv2.MARKER_CROSS,
                12,
                1,
            )
            if first_target is None:
                first_target = (cx, cy)
            # size label
            label = f"{det.width_mm:.1f}x{det.height_mm:.1f} mm"
            cv2.putText(
                frame,
                label,
                (cx - 50, cy - 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
            )

        # --- measurement points (green numbered circles) ---
        if measurements:
            for m in measurements:
                if m.pixel_x is not None and m.pixel_y is not None:
                    px = int(m.pixel_x)
                    py = int(m.pixel_y)
                else:
                    continue
                color = (0, 220, 100)
                cv2.circle(frame, (px, py), 10, color, -1)
                cv2.circle(frame, (px, py), 10, (255, 255, 255), 1)
                idx_label = str(m.waypoint_index + 1)
                cv2.putText(
                    frame,
                    idx_label,
                    (px - 4, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (0, 0, 0),
                    1,
                )
                if first_target is None:
                    first_target = (px, py)
                if m.scan_result:
                    summary = _scan_summary(m.scan_result)
                    cv2.putText(
                        frame,
                        summary,
                        (px + 14, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.35,
                        (200, 200, 200),
                        1,
                    )

        # --- starting point (orange diamond + "START" label) ---
        if starting_point:
            sx, sy = int(starting_point[0]), int(starting_point[1])
            size = 12
            diamond = np.array(
                [
                    [sx, sy - size],
                    [sx + size, sy],
                    [sx, sy + size],
                    [sx - size, sy],
                ],
                dtype=np.int32,
            )
            cv2.fillPoly(frame, [diamond], (0, 140, 255))
            cv2.polylines(frame, [diamond], True, (255, 255, 255), 2)
            cv2.putText(
                frame,
                "START",
                (sx + 16, sy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 140, 255),
                2,
            )
            if first_target:
                _draw_dashed_line(frame, (sx, sy), first_target, (255, 255, 255), 1, 10)

        _, out = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return out.tobytes()


def _scan_summary(scan_result: dict) -> str:
    """Extract a short human-readable label from a DMS scan result dict."""
    compound = scan_result.get("compound", scan_result.get("name", ""))
    ppb = scan_result.get("ppb", scan_result.get("concentration", ""))
    if compound and ppb:
        return f"{compound} {ppb} ppb"
    if compound:
        return str(compound)
    return "scan"


def _draw_dashed_line(
    img: np.ndarray,
    pt1: tuple,
    pt2: tuple,
    color: tuple,
    thickness: int = 1,
    gap: int = 10,
) -> None:
    """Draw a dashed line between two points on a cv2 image."""
    import cv2
    import numpy as np

    x1, y1 = pt1
    x2, y2 = pt2
    dist = np.hypot(x2 - x1, y2 - y1)
    if dist < 1:
        return
    dx = (x2 - x1) / dist
    dy = (y2 - y1) / dist
    num_segments = int(dist // gap)
    for i in range(0, num_segments, 2):
        sx = int(x1 + dx * gap * i)
        sy = int(y1 + dy * gap * i)
        ex = int(x1 + dx * gap * min(i + 1, num_segments))
        ey = int(y1 + dy * gap * min(i + 1, num_segments))
        cv2.line(img, (sx, sy), (ex, ey), color, thickness)
