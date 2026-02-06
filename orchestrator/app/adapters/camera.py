from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class CaptureResult:
    ok: bool
    image_path: Optional[str] = None
    error: Optional[str] = None


class CameraAdapter:
    """
    Minimal capture based on nenabot-main/camera_detection/main.py.
    """

    def __init__(self, device_index: int = 0, output_dir: str = "data/images") -> None:
        self._device_index = device_index
        self._output_dir = Path(output_dir)

    def capture(self) -> CaptureResult:
        try:
            import cv2
        except Exception as exc:  # pragma: no cover - optional dependency
            return CaptureResult(False, error=f"OpenCV not available: {exc}")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(self._device_index)
        if not cap.isOpened():
            return CaptureResult(False, error="Unable to open camera")

        ok, frame = cap.read()
        cap.release()
        if not ok:
            return CaptureResult(False, error="Failed to read frame")

        filename = f"capture_{datetime.utcnow().isoformat().replace(':', '-')}.jpg"
        path = self._output_dir / filename
        cv2.imwrite(str(path), frame)
        return CaptureResult(True, image_path=str(path))
