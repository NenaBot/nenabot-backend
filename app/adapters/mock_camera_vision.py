from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - optional in constrained envs
    cv2 = None

from app.adapters.camera_vision import (
    FIXED_CALIBRATION_POINTS,
    CalibrationTarget,
    CaptureResult,
    CheckerboardResult,
    Corner,
    DetectionResult,
    DetectionResults,
)


class MockCameraVisionAdapter:
    """In-memory camera+vision adapter for frontend/dev mock mode."""

    def __init__(
        self,
        device_index: int = 0,
        output_dir: str = "data/images",
        intrinsics_path: str | None = None,
        mock_image_path: str | None = None,
        frame_width: int = 1920,
        frame_height: int = 1080,
        checkerboard_size: tuple[int, int] = (8, 6),
        checkerboard_square_mm: float = 34.0,
    ) -> None:
        # Canonical mock detection points at 1280x720. These are scaled for other
        # resolutions so frontend overlays remain stable in mock mode.
        self._canonical_detection_corners = [
            (920, 434),
            (1162, 438),
            (1160, 754),
            (919, 753),
        ]
        self._checkerboard_point_ratios = {
            (1, 0): (0.110, 0.700),
            (1, 6): (0.180, 0.700),
            (5, 7): (0.180, 0.800),
            (5, 0): (0.110, 0.800),
        }

        self._device_index = device_index
        self._output_dir = Path(output_dir)
        self._intrinsics_path = intrinsics_path or "data/calibration/camera_params.json"
        self._mock_image_path = mock_image_path
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._checkerboard_size = checkerboard_size
        self._checkerboard_square_mm = checkerboard_square_mm
        self._source_image_bytes: bytes | None = None
        self._detection_confidence = 0.95

        self._camera_matrix = np.array(
            [
                [1000.0, 0.0, frame_width / 2.0],
                [0.0, 1000.0, frame_height / 2.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self._dist_coeff = np.zeros((1, 5), dtype=np.float64)
        self._fallback_jpeg_bytes = base64.b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBUQEBAVFhUVFRUVFRUVFRUVFRUWFxUVFRUYHSggGBolGxUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGhAQGy0lICUtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIABQAFAMBIgACEQEDEQH/xAAXAAADAQAAAAAAAAAAAAAAAAAAAQID/8QAFhEBAQEAAAAAAAAAAAAAAAAAAAER/9oADAMBAAIQAxAAAAHnA//EABgQAQADAQAAAAAAAAAAAAAAAAEAESEx/9oACAEBAAEFAq8v/8QAFhEBAQEAAAAAAAAAAAAAAAAAABEh/9oACAEDAQE/AT//xAAVEQEBAAAAAAAAAAAAAAAAAAAQIf/aAAgBAgEBPwEf/8QAHBABAAICAwAAAAAAAAAAAAAAAREAITFBQWFx/9oACAEBAAY/AhN3NQf/xAAZEAEAAwEBAAAAAAAAAAAAAAABABEhMUH/2gAIAQEAAT8hY0fM5a4m2p0l/9oADAMBAAIAAwAAABAf/8QAFhEBAQEAAAAAAAAAAAAAAAAAABEh/9oACAEDAQE/EGf/xAAXEQEBAQEAAAAAAAAAAAAAAAABABEh/9oACAECAQE/EK9f/8QAGxABAQADAAMAAAAAAAAAAAAAAREAITFBUWH/2gAIAQEAAT8QkW0xv0V2kQ0w3rG8nQqzQK9qv//Z"
        )

        self._frame = self._load_mock_image_frame()
        self._detection_corners = self._build_default_detection_corners()
        self._checkerboard_points = self._build_checkerboard_points()
        self._camera_frame = self._render_camera_frame(self._frame)
        self._camera_jpeg_bytes = self._encode_jpeg(self._camera_frame)
        self._detection_frame = self._render_detection_frame(self._frame)
        self._detection_jpeg_bytes = self._encode_jpeg(self._detection_frame)
        self._refresh_detection_outputs()

    def _resolve_mock_image_path(self) -> Path | None:
        if self._mock_image_path:
            path = Path(self._mock_image_path)
            if path.exists():
                return path

        backend_root = Path(__file__).resolve().parents[2]
        candidates = [
            Path("data/calibration/mock.jpeg"),
            backend_root / "data/calibration/mock.jpeg",
            backend_root / "app/assets/mock.jpeg",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _load_mock_image_frame(self) -> np.ndarray:
        image_path = self._resolve_mock_image_path()
        if image_path is not None:
            self._source_image_bytes = image_path.read_bytes()

        if cv2 is not None and self._source_image_bytes:
            image_data = np.frombuffer(self._source_image_bytes, dtype=np.uint8)
            decoded = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
            if decoded is not None:
                return cv2.resize(
                    decoded,
                    (self._frame_width, self._frame_height),
                    interpolation=cv2.INTER_AREA,
                )
        return np.zeros((self._frame_height, self._frame_width, 3), dtype=np.uint8)

    def _build_default_detection_corners(self) -> list[tuple[int, int]]:
        base_width = 1920.0
        base_height = 1080.0
        return [
            (
                int(round(self._frame_width * (x / base_width))),
                int(round(self._frame_height * (y / base_height))),
            )
            for x, y in self._canonical_detection_corners
        ]

    @staticmethod
    def _estimate_size_from_corners(
        corners: list[tuple[int, int]],
    ) -> tuple[float, float]:
        if len(corners) != 4:
            return (80.0, 40.0)

        points = np.array(corners, dtype=np.float64)
        width = float(
            (
                np.linalg.norm(points[1] - points[0])
                + np.linalg.norm(points[2] - points[3])
            )
            / 2.0
        )
        height = float(
            (
                np.linalg.norm(points[3] - points[0])
                + np.linalg.norm(points[2] - points[1])
            )
            / 2.0
        )
        return (max(width, 1.0), max(height, 1.0))

    def _refresh_detection_outputs(self) -> None:
        self._detection_corners = self._build_default_detection_corners()
        self._detection_confidence = 0.95
        self._detection_frame = self._render_detection_frame(self._frame)
        self._detection_jpeg_bytes = self._encode_jpeg(self._detection_frame)

    def _build_checkerboard_points(self) -> dict[tuple[int, int], tuple[float, float]]:
        return {
            key: (self._frame_width * px, self._frame_height * py)
            for key, (px, py) in self._checkerboard_point_ratios.items()
        }

    @staticmethod
    def _watermark_text_position(frame: np.ndarray, text: str) -> tuple[int, int]:
        if cv2 is None:
            return (20, 40)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.6
        thickness = 3
        (text_width, text_height), _ = cv2.getTextSize(
            text,
            font,
            font_scale,
            thickness,
        )
        x = max(10, (frame.shape[1] - text_width) // 2)
        y = max(text_height + 10, (frame.shape[0] + text_height) // 2)
        return (x, y)

    def _apply_mockmode_watermark(self, frame: np.ndarray) -> np.ndarray:
        if cv2 is None:
            return frame
        output = frame.copy()
        label = "MOCKMODE"
        x, y = self._watermark_text_position(output, label)
        cv2.putText(
            output,
            label,
            (x + 2, y + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.6,
            (0, 0, 0),
            4,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            label,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.6,
            (0, 0, 255),
            3,
            cv2.LINE_AA,
        )
        return output

    def _render_camera_frame(self, base_frame: np.ndarray) -> np.ndarray:
        return self._apply_mockmode_watermark(base_frame)

    def _render_detection_frame(self, base_frame: np.ndarray) -> np.ndarray:
        frame = self._apply_mockmode_watermark(base_frame)
        if cv2 is None:
            return frame

        corners = np.array(self._detection_corners, dtype=np.int32)
        cv2.polylines(frame, [corners.reshape(-1, 1, 2)], True, (0, 255, 255), 2)
        for index, (x, y) in enumerate(self._detection_corners, start=1):
            cv2.circle(frame, (x, y), 7, (0, 255, 0), -1)
            cv2.putText(
                frame,
                str(index),
                (x + 10, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        return frame

    def _encode_jpeg(self, frame: np.ndarray) -> bytes:
        if cv2 is not None:
            ok, encoded = cv2.imencode(".jpg", frame)
            if ok:
                return bytes(encoded)
        if self._source_image_bytes:
            return self._source_image_bytes
        return self._fallback_jpeg_bytes

    @property
    def intrinsics_loaded(self) -> bool:
        return True

    @property
    def intrinsics_error(self) -> str | None:
        return None

    @property
    def intrinsics_path(self) -> str | None:
        return self._intrinsics_path

    @property
    def intrinsics_resolution(self) -> tuple[int, int] | None:
        return (self._frame_width, self._frame_height)

    @property
    def checkerboard_size(self) -> tuple[int, int]:
        return self._checkerboard_size

    @property
    def checkerboard_square_mm(self) -> float:
        return self._checkerboard_square_mm

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def camera_matrix(self) -> np.ndarray:
        return self._camera_matrix

    @property
    def dist_coeff(self) -> np.ndarray:
        return self._dist_coeff

    def ping(self) -> CaptureResult:
        return CaptureResult(ok=True)

    def get_latest_frame(self, timeout_s: float = 1.0, *, ensure_capture: bool = True):
        return self._camera_frame.copy()

    def get_latest_frame_bytes(self) -> bytes:
        return self._camera_jpeg_bytes

    def frame_to_base64(self, frame: np.ndarray) -> str:
        return base64.b64encode(self._encode_jpeg(frame)).decode("ascii")

    def capture(self) -> CaptureResult:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        filename = (
            f"capture_{datetime.now(timezone.utc).isoformat().replace(':', '-')}.jpg"
        )
        path = self._output_dir / filename
        path.write_bytes(self._camera_jpeg_bytes)
        return CaptureResult(ok=True, image_path=str(path))

    def detect(self, image_path: str) -> DetectionResults:
        return self.detect_latest()

    def detect_latest(self) -> DetectionResults:
        self._refresh_detection_outputs()
        corner_objects = [
            Corner(x=float(x), y=float(y)) for x, y in self._detection_corners
        ]
        width_mm, height_mm = self._estimate_size_from_corners(self._detection_corners)
        center_x = float(sum(x for x, _ in self._detection_corners) / 4.0)
        center_y = float(sum(y for _, y in self._detection_corners) / 4.0)
        return DetectionResults(
            ok=True,
            detections=[
                DetectionResult(
                    corners=corner_objects,
                    width_mm=width_mm,
                    height_mm=height_mm,
                    center_x=center_x,
                    center_y=center_y,
                    confidence=self._detection_confidence,
                )
            ],
            image_base64=base64.b64encode(self._detection_jpeg_bytes).decode("ascii"),
            error=None,
        )

    def checkerboard_visible(self) -> bool:
        return True

    def checkerboard_status(self) -> dict[str, bool | str | None]:
        return {"visible": True, "error": None}

    def find_checkerboard(self, frame: np.ndarray) -> CheckerboardResult:
        targets: list[CalibrationTarget] = []
        for step, (row, col) in enumerate(FIXED_CALIBRATION_POINTS, start=1):
            x, y = self._checkerboard_points[(row, col)]
            targets.append(CalibrationTarget(x=x, y=y, row=row, col=col, step=step))

        return CheckerboardResult(
            ok=True,
            corners=[Corner(x=t.x, y=t.y) for t in targets],
            target_points=[Corner(x=t.x, y=t.y) for t in targets],
            target_specs=targets,
            image_size=(self._frame_width, self._frame_height),
            error=None,
        )

    @staticmethod
    def _orientation_targets(
        targets: list[CalibrationTarget],
    ) -> tuple[CalibrationTarget, CalibrationTarget, CalibrationTarget] | None:
        candidates: list[
            tuple[CalibrationTarget, CalibrationTarget, CalibrationTarget]
        ] = []
        for origin in targets:
            col_targets = [
                target
                for target in targets
                if target.row == origin.row and target.col > origin.col
            ]
            row_targets = [
                target
                for target in targets
                if target.col == origin.col and target.row > origin.row
            ]
            if not col_targets or not row_targets:
                continue

            col_target = max(col_targets, key=lambda target: target.col - origin.col)
            row_target = max(row_targets, key=lambda target: target.row - origin.row)
            candidates.append((origin, col_target, row_target))

        if not candidates:
            return None

        return min(candidates, key=lambda item: (item[0].row, item[0].col))

    async def stream_camera(self) -> AsyncGenerator[bytes, None]:
        while True:
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + self._camera_jpeg_bytes
                + b"\r\n"
            )
            await asyncio.sleep(0.1)

    async def stream_detection(self) -> AsyncGenerator[bytes, None]:
        while True:
            self._refresh_detection_outputs()
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                + self._detection_jpeg_bytes
                + b"\r\n"
            )
            await asyncio.sleep(0.15)
