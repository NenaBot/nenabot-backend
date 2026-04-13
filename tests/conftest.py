from __future__ import annotations

import pytest


class _BlockedVideoCapture:
    """OpenCV VideoCapture stub used to prevent real camera access in tests."""

    def __init__(self, *_args, **_kwargs) -> None:
        self._opened = False

    def isOpened(self) -> bool:
        return self._opened

    def release(self) -> None:
        return None

    def set(self, *_args, **_kwargs) -> bool:
        return False

    def read(self):
        return False, None


@pytest.fixture(autouse=True)
def block_real_camera_access(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
):
    """Block camera hardware in tests unless explicitly running hardware/integration checks."""
    if request.node.get_closest_marker("hardware"):
        return
    if request.node.get_closest_marker("integration"):
        return

    try:
        import cv2
    except Exception:
        return

    monkeypatch.setattr(cv2, "VideoCapture", _BlockedVideoCapture)
