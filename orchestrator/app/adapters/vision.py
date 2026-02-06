from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PoseEstimate:
    ok: bool
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    r: float = 0.0
    confidence: float = 0.0
    error: Optional[str] = None


class VisionAdapter:
    """
    Example ArUco-based pose detection using camera_detection/main.py as reference.
    This is a placeholder that returns a dummy pose when a marker is detected.
    """

    def __init__(self, marker_size_mm: float = 48.0) -> None:
        self._marker_size_mm = marker_size_mm

    def detect(self, image_path: str) -> PoseEstimate:
        try:
            import cv2
        except Exception as exc:  # pragma: no cover - optional dependency
            return PoseEstimate(False, error=f"OpenCV not available: {exc}")

        image = cv2.imread(image_path)
        if image is None:
            return PoseEstimate(False, error="Unable to read image")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector_params = cv2.aruco.DetectorParameters()
        detector = cv2.aruco.ArucoDetector(aruco_dict, detector_params)
        corners, ids, _ = detector.detectMarkers(gray)

        if ids is None or len(corners) == 0:
            return PoseEstimate(False, error="No marker detected")

        # Placeholder pose: use marker center as X/Y in pixels, Z/R dummy.
        marker_corners = corners[0][0]
        center_x = float(marker_corners[:, 0].mean())
        center_y = float(marker_corners[:, 1].mean())
        return PoseEstimate(True, x=center_x, y=center_y, z=0.0, r=0.0, confidence=0.7)
