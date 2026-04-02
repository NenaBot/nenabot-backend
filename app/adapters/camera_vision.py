from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

FIXED_CALIBRATION_POINTS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, 6),
    (5, 7),
    (5, 0),
)


@dataclass
class CaptureResult:
    ok: bool
    image_path: str | None = None
    error: str | None = None


@dataclass
class Corner:
    x: float
    y: float


@dataclass
class CalibrationTarget:
    x: float
    y: float
    row: int
    col: int
    step: int

    @property
    def label(self) -> str:
        return f"P{self.step} ({self.row},{self.col})"


@dataclass
class DetectionResult:
    corners: list[Corner] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    confidence: float = 0.0


@dataclass
class DetectionResults:
    ok: bool
    detections: list[DetectionResult] = field(default_factory=list)
    image_base64: str | None = None
    error: str | None = None


@dataclass
class CheckerboardResult:
    ok: bool
    corners: list[Corner] = field(default_factory=list)
    target_points: list[Corner] = field(default_factory=list)
    target_specs: list[CalibrationTarget] = field(default_factory=list)
    image_size: tuple[int, int] | None = None
    error: str | None = None


@dataclass
class IntrinsicCalibration:
    path: str
    camera_matrix: np.ndarray
    dist_coeff: np.ndarray
    resolution: tuple[int, int]
    checkerboard_size: tuple[int, int]
    square_size_mm: float


class CameraVisionAdapter:
    """Shared camera capture with checkerboard and battery detection helpers."""

    def __init__(
        self,
        device_index: int = 0,
        output_dir: str = "data/images",
        intrinsics_path: str | None = None,
        frame_width: int = 1280,
        frame_height: int = 720,
        checkerboard_size: tuple[int, int] = (8, 6),
        checkerboard_square_mm: float = 34.0,
    ) -> None:
        self._device_index = device_index
        self._output_dir = Path(output_dir)
        self._intrinsics_path = intrinsics_path
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._checkerboard_size = checkerboard_size
        self._checkerboard_square_mm = checkerboard_square_mm

        self._intrinsics: IntrinsicCalibration | None = None
        self._intrinsics_error: str | None = None
        self._load_intrinsics()

        self._capture_thread: threading.Thread | None = None
        self._capture_lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._capture_ready = threading.Event()
        self._capture_running = False
        self._capture_error: str | None = None

    # ---- intrinsics ----

    def _load_intrinsics(self) -> None:
        try:
            import numpy as np
        except Exception as exc:  # pragma: no cover
            self._intrinsics = None
            self._intrinsics_error = f"NumPy not available: {exc}"
            return

        if not self._intrinsics_path:
            self._intrinsics = None
            self._intrinsics_error = "Intrinsic calibration path not configured"
            return

        path = Path(self._intrinsics_path)
        if not path.exists():
            self._intrinsics = None
            self._intrinsics_error = f"Intrinsic calibration not found: {path}"
            return

        try:
            data = json.loads(path.read_text())
            camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
            dist_coeff = np.array(data["dist_coeff"], dtype=np.float64)
            resolution_raw = data["resolution"]
            resolution = (int(resolution_raw[0]), int(resolution_raw[1]))
        except Exception as exc:
            self._intrinsics = None
            self._intrinsics_error = f"Invalid intrinsic calibration file: {exc}"
            return

        checkerboard = data.get("checkerboard") or {}
        checkerboard_size = tuple(
            checkerboard.get("inner_corners", self._checkerboard_size)
        )
        square_size_mm = float(
            checkerboard.get("square_size_mm", self._checkerboard_square_mm)
        )

        self._intrinsics = IntrinsicCalibration(
            path=str(path),
            camera_matrix=camera_matrix,
            dist_coeff=dist_coeff,
            resolution=resolution,
            checkerboard_size=(int(checkerboard_size[0]), int(checkerboard_size[1])),
            square_size_mm=square_size_mm,
        )
        self._frame_width = resolution[0]
        self._frame_height = resolution[1]
        self._intrinsics_error = None

    @property
    def intrinsics_loaded(self) -> bool:
        return self._intrinsics is not None

    @property
    def intrinsics_error(self) -> str | None:
        return self._intrinsics_error

    @property
    def intrinsics_path(self) -> str | None:
        return self._intrinsics.path if self._intrinsics else self._intrinsics_path

    @property
    def intrinsics_resolution(self) -> tuple[int, int] | None:
        return self._intrinsics.resolution if self._intrinsics else None

    @property
    def checkerboard_size(self) -> tuple[int, int]:
        if self._intrinsics:
            return self._intrinsics.checkerboard_size
        return self._checkerboard_size

    @property
    def checkerboard_square_mm(self) -> float:
        if self._intrinsics:
            return self._intrinsics.square_size_mm
        return self._checkerboard_square_mm

    @property
    def camera_matrix(self) -> np.ndarray | None:
        return self._intrinsics.camera_matrix if self._intrinsics else None

    @property
    def dist_coeff(self) -> np.ndarray | None:
        return self._intrinsics.dist_coeff if self._intrinsics else None

    # ---- shared capture ----

    def _capture_loop(self) -> None:
        import cv2

        cap = cv2.VideoCapture(self._device_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._frame_height)
        try:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        except Exception:  # pragma: no cover
            logger.debug("Failed to disable autofocus", exc_info=True)

        if not cap.isOpened():
            self._capture_error = "Unable to open camera"
            self._capture_running = False
            self._capture_ready.set()
            cap.release()
            return

        self._capture_error = None
        self._capture_running = True
        self._capture_ready.set()

        try:
            while self._capture_running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue
                with self._frame_lock:
                    self._latest_frame = frame.copy()
        finally:
            cap.release()
            self._capture_running = False

    def _ensure_capture_running(self) -> CaptureResult:
        try:
            import cv2  # noqa: F401
        except Exception as exc:  # pragma: no cover
            return CaptureResult(False, error=f"OpenCV not available: {exc}")

        with self._capture_lock:
            if self._capture_thread and self._capture_thread.is_alive():
                return CaptureResult(True)

            self._capture_ready.clear()
            self._capture_error = None
            self._capture_running = True
            self._capture_thread = threading.Thread(
                target=self._capture_loop,
                daemon=True,
            )
            self._capture_thread.start()

        self._capture_ready.wait(timeout=1.0)
        if self._capture_error:
            return CaptureResult(False, error=self._capture_error)
        return CaptureResult(True)

    def ping(self) -> CaptureResult:
        return self._ensure_capture_running()

    def get_latest_frame(self, timeout_s: float = 1.0) -> np.ndarray | None:
        result = self._ensure_capture_running()
        if not result.ok:
            return None

        deadline = time.monotonic() + max(timeout_s, 0.0)
        while time.monotonic() <= deadline:
            with self._frame_lock:
                if self._latest_frame is not None:
                    return self._latest_frame.copy()
            time.sleep(0.02)
        return None

    def get_latest_frame_bytes(self) -> bytes | None:
        import cv2

        frame = self.get_latest_frame()
        if frame is None:
            return None
        ok, jpeg = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return jpeg.tobytes()

    # ---- capture and detection ----

    def capture(self) -> CaptureResult:
        import cv2

        frame = self.get_latest_frame()
        if frame is None:
            return CaptureResult(False, error="No camera frame available")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        filename = (
            f"capture_{datetime.now(timezone.utc).isoformat().replace(':', '-')}.jpg"
        )
        path = self._output_dir / filename
        if not cv2.imwrite(str(path), frame):
            return CaptureResult(False, error="Failed to write frame")
        return CaptureResult(True, image_path=str(path))

    def detect(self, image_path: str) -> DetectionResults:
        import cv2

        frame = cv2.imread(image_path)
        if frame is None:
            return DetectionResults(False, error="Unable to read image")
        return self.detect_frame(frame)

    def detect_frame(self, frame: np.ndarray) -> DetectionResults:
        detections = self._detect_batteries(frame)
        if not detections:
            return DetectionResults(False, error="No battery contour detected")
        return DetectionResults(True, detections=detections)

    def detect_latest(self) -> DetectionResults:
        frame = self.get_latest_frame()
        if frame is None:
            return DetectionResults(False, error="No camera frame available")

        result = self.detect_frame(frame)
        try:
            result.image_base64 = self.frame_to_base64(frame)
        except Exception:  # pragma: no cover
            logger.debug("Image encoding failed", exc_info=True)
        return result

    def _detect_batteries(self, frame: np.ndarray) -> list[DetectionResult]:
        import cv2
        import numpy as np

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
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
            width_px, height_px = rect[1]
            if width_px == 0 or height_px == 0:
                continue

            aspect = max(width_px, height_px) / min(width_px, height_px)
            if aspect < 1.05 or aspect > 3.5:
                continue

            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            if cv2.mean(gray, mask=mask)[0] > 150:
                continue

            box = cv2.boxPoints(rect)
            detections.append(
                DetectionResult(
                    corners=[Corner(x=float(pt[0]), y=float(pt[1])) for pt in box],
                    width_mm=float(width_px),
                    height_mm=float(height_px),
                    center_x=float(rect[0][0]),
                    center_y=float(rect[0][1]),
                    confidence=0.7,
                )
            )

        return detections

    # ---- checkerboard ----

    def checkerboard_visible(self) -> bool:
        frame = self.get_latest_frame(timeout_s=0.5)
        if frame is None:
            return False
        return self.find_checkerboard(frame).ok

    def checkerboard_status(self) -> dict[str, bool | str | None]:
        frame = self.get_latest_frame(timeout_s=0.5)
        if frame is None:
            return {"visible": False, "error": "No camera frame available"}

        result = self.find_checkerboard(frame)
        return {"visible": result.ok, "error": result.error}

    def find_checkerboard(self, frame: np.ndarray) -> CheckerboardResult:
        import cv2

        if self._intrinsics:
            expected_size = self._intrinsics.resolution
            actual_size = (frame.shape[1], frame.shape[0])
            if actual_size != expected_size:
                return CheckerboardResult(
                    ok=False,
                    image_size=actual_size,
                    error=(
                        "Camera frame resolution "
                        f"{actual_size[0]}x{actual_size[1]} does not match intrinsic calibration "
                        f"{expected_size[0]}x{expected_size[1]}"
                    ),
                )

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, self.checkerboard_size, None)
        if not found or corners is None:
            return CheckerboardResult(
                ok=False,
                image_size=(frame.shape[1], frame.shape[0]),
                error="Checkerboard not found",
            )

        criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
            30,
            0.001,
        )
        refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

        all_corners = [
            Corner(x=float(point[0][0]), y=float(point[0][1])) for point in refined
        ]
        target_specs = self._extract_target_specs(refined)
        targets = [Corner(x=target.x, y=target.y) for target in target_specs]

        return CheckerboardResult(
            ok=True,
            corners=all_corners,
            target_points=targets,
            target_specs=target_specs,
            image_size=(frame.shape[1], frame.shape[0]),
        )

    def _extract_target_specs(self, corners: np.ndarray) -> list[CalibrationTarget]:
        cols, _rows = self.checkerboard_size
        targets: list[CalibrationTarget] = []
        for step, (row, col) in enumerate(FIXED_CALIBRATION_POINTS, start=1):
            flat_index = row * cols + col
            point = corners[flat_index][0]
            targets.append(
                CalibrationTarget(
                    x=float(point[0]),
                    y=float(point[1]),
                    row=row,
                    col=col,
                    step=step,
                )
            )
        return targets

    # ---- streaming ----

    def _error_frame(self, text: str) -> bytes:
        import cv2
        import numpy as np

        frame = np.zeros((self._frame_height, self._frame_width, 3), dtype=np.uint8)
        lines = text.split("\n")
        y0 = self._frame_height // 2 - 20 * (len(lines) - 1) // 2
        for index, line in enumerate(lines):
            cv2.putText(
                frame,
                line,
                (40, y0 + index * 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (80, 80, 255),
                2,
            )
        _, jpeg = cv2.imencode(".jpg", frame)
        return jpeg.tobytes()

    async def stream_camera(self) -> AsyncGenerator[bytes, None]:
        import cv2

        result = self._ensure_capture_running()
        if not result.ok:
            error = self._error_frame(result.error or "Camera not available")
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + error + b"\r\n"
            return

        while True:
            frame = self.get_latest_frame(timeout_s=1.0)
            if frame is None:
                error = self._error_frame("No camera frame available")
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + error + b"\r\n"
                await asyncio.sleep(0.2)
                continue

            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + jpeg.tobytes()
                + b"\r\n"
            )
            await asyncio.sleep(0.033)

    async def stream_detection(self) -> AsyncGenerator[bytes, None]:
        import cv2

        result = self._ensure_capture_running()
        if not result.ok:
            error = self._error_frame(result.error or "Camera not available")
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + error + b"\r\n"
            return

        while True:
            frame = self.get_latest_frame(timeout_s=1.0)
            if frame is None:
                error = self._error_frame("No camera frame available")
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + error + b"\r\n"
                await asyncio.sleep(0.2)
                continue

            annotated = self.detect_live(frame)
            _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + jpeg.tobytes()
                + b"\r\n"
            )
            await asyncio.sleep(0.033)

    def detect_live(self, frame: np.ndarray) -> np.ndarray:
        import cv2
        import numpy as np

        annotated = frame.copy()

        checkerboard = self.find_checkerboard(frame)
        if checkerboard.ok:
            pts = np.array([[int(c.x), int(c.y)] for c in checkerboard.corners])
            for point in pts:
                cv2.circle(annotated, tuple(point), 3, (255, 0, 255), -1)
            for target in checkerboard.target_specs:
                px = int(target.x)
                py = int(target.y)
                cv2.circle(annotated, (px, py), 10, (0, 140, 255), 2)
                cv2.putText(
                    annotated,
                    target.label,
                    (px + 10, py - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 140, 255),
                    2,
                )

            if len(checkerboard.target_specs) >= 4:
                p1 = checkerboard.target_specs[0]
                p2 = checkerboard.target_specs[1]
                p4 = checkerboard.target_specs[3]
                cv2.arrowedLine(
                    annotated,
                    (int(p1.x), int(p1.y)),
                    (int(p2.x), int(p2.y)),
                    (38, 189, 248),
                    2,
                    tipLength=0.03,
                )
                cv2.arrowedLine(
                    annotated,
                    (int(p1.x), int(p1.y)),
                    (int(p4.x), int(p4.y)),
                    (34, 197, 94),
                    2,
                    tipLength=0.03,
                )
                cv2.putText(
                    annotated,
                    "col+",
                    (int((p1.x + p2.x) / 2), int((p1.y + p2.y) / 2) - 12),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (38, 189, 248),
                    2,
                )
                cv2.putText(
                    annotated,
                    "row+",
                    (int((p1.x + p4.x) / 2) + 8, int((p1.y + p4.y) / 2)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (34, 197, 94),
                    2,
                )

        for detection in self._detect_batteries(frame):
            if len(detection.corners) >= 4:
                points = np.array(
                    [[int(c.x), int(c.y)] for c in detection.corners],
                    dtype=np.int32,
                )
                cv2.drawContours(annotated, [points], 0, (0, 255, 255), 2)

            cv2.drawMarker(
                annotated,
                (int(detection.center_x), int(detection.center_y)),
                (0, 255, 255),
                cv2.MARKER_CROSS,
                12,
                1,
            )

        return annotated

    # ---- encoding helpers ----

    @staticmethod
    def frame_to_base64(frame: np.ndarray) -> str:
        import cv2
        import base64

        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise RuntimeError("Failed to encode frame")
        return base64.b64encode(jpeg.tobytes()).decode("ascii")

    @staticmethod
    def render_overlay(
        jpeg_bytes: bytes,
        detections: list[DetectionResult],
        measurements: list | None = None,
        starting_point: tuple[float, float] | None = None,
    ) -> bytes:
        import cv2
        import numpy as np

        buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            return jpeg_bytes

        first_target: tuple[int, int] | None = None
        for detection in detections:
            if len(detection.corners) >= 4:
                points = np.array(
                    [[int(c.x), int(c.y)] for c in detection.corners],
                    dtype=np.int32,
                )
                cv2.drawContours(frame, [points], 0, (0, 255, 255), 2)

            cx = int(detection.center_x)
            cy = int(detection.center_y)
            cv2.drawMarker(frame, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 12, 1)
            if first_target is None:
                first_target = (cx, cy)

        if measurements:
            for measurement in measurements:
                if measurement.pixel_x is None or measurement.pixel_y is None:
                    continue
                px = int(measurement.pixel_x)
                py = int(measurement.pixel_y)
                cv2.circle(frame, (px, py), 10, (0, 220, 100), -1)
                cv2.circle(frame, (px, py), 10, (255, 255, 255), 1)
                cv2.putText(
                    frame,
                    str(measurement.waypoint_index + 1),
                    (px - 4, py + 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (0, 0, 0),
                    1,
                )
                if first_target is None:
                    first_target = (px, py)

        if starting_point:
            sx, sy = int(starting_point[0]), int(starting_point[1])
            diamond = np.array(
                [[sx, sy - 12], [sx + 12, sy], [sx, sy + 12], [sx - 12, sy]],
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
                _draw_dashed_line(frame, (sx, sy), first_target, (255, 255, 255), 1)

        _, out = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return out.tobytes()


def _draw_dashed_line(
    image: np.ndarray,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    thickness: int = 1,
    gap: int = 10,
) -> None:
    import cv2
    import numpy as np

    x1, y1 = start
    x2, y2 = end
    distance = np.hypot(x2 - x1, y2 - y1)
    if distance < 1:
        return

    dx = (x2 - x1) / distance
    dy = (y2 - y1) / distance
    segment_count = int(distance // gap)
    for index in range(0, segment_count, 2):
        sx = int(x1 + dx * gap * index)
        sy = int(y1 + dy * gap * index)
        ex = int(x1 + dx * gap * min(index + 1, segment_count))
        ey = int(y1 + dy * gap * min(index + 1, segment_count))
        cv2.line(image, (sx, sy), (ex, ey), color, thickness)
