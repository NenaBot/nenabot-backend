from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from app.adapters.mock_camera_vision import MockCameraVisionAdapter


class _FakeCv2:
    IMREAD_COLOR = 1
    INTER_AREA = 2

    def __init__(self, captured_payloads: list[bytes]) -> None:
        self._captured_payloads = captured_payloads

    def imdecode(self, image_data: np.ndarray, flags: int) -> np.ndarray:
        self._captured_payloads.append(bytes(image_data))
        return np.ones((2, 2, 3), dtype=np.uint8)

    def resize(
        self,
        frame: np.ndarray,
        size: tuple[int, int],
        interpolation: int,
    ) -> np.ndarray:
        width, height = size
        return np.full((height, width, 3), 7, dtype=np.uint8)


def _build_adapter(
    *,
    frame_width: int = 8,
    frame_height: int = 6,
    mock_image_path: str | None = None,
) -> MockCameraVisionAdapter:
    adapter = MockCameraVisionAdapter.__new__(MockCameraVisionAdapter)
    adapter._frame_width = frame_width
    adapter._frame_height = frame_height
    adapter._mock_image_path = mock_image_path
    adapter._source_image_bytes = None
    return adapter


def _write_mock_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_load_mock_image_prefers_mock_jpeg_over_mock_jpg(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_file(tmp_path / "data/calibration/mock.jpg", b"jpg-bytes")
    _write_mock_file(tmp_path / "data/calibration/mock.jpeg", b"jpeg-bytes")

    captured_payloads: list[bytes] = []
    monkeypatch.setattr(
        "app.adapters.mock_camera_vision.cv2",
        _FakeCv2(captured_payloads),
    )

    adapter = _build_adapter(frame_width=5, frame_height=4)
    frame = adapter._load_mock_image_frame()

    assert captured_payloads == [b"jpeg-bytes"]
    assert frame.shape == (4, 5, 3)


def test_load_mock_image_ignores_mock_jpg_when_jpeg_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_mock_file(tmp_path / "data/calibration/mock.jpg", b"jpg-only")

    captured_payloads: list[bytes] = []
    monkeypatch.setattr(
        "app.adapters.mock_camera_vision.cv2",
        _FakeCv2(captured_payloads),
    )

    adapter = _build_adapter(
        frame_width=7,
        frame_height=3,
        mock_image_path=str(tmp_path / "data/calibration/does-not-exist.jpeg"),
    )
    frame = adapter._load_mock_image_frame()

    assert captured_payloads
    assert captured_payloads != [b"jpg-only"]
    assert frame.shape == (3, 7, 3)


def test_detect_latest_refreshes_detection_outputs(monkeypatch) -> None:
    adapter = MockCameraVisionAdapter.__new__(MockCameraVisionAdapter)
    adapter._detection_jpeg_bytes = b"mock-detection-bytes"
    adapter._detection_corners = [(0, 0), (10, 0), (10, 4), (0, 4)]
    adapter._detection_confidence = 0.91

    refresh_calls = {"count": 0}

    def fake_refresh() -> None:
        refresh_calls["count"] += 1
        adapter._detection_corners = [(1, 1), (9, 1), (9, 5), (1, 5)]
        adapter._detection_confidence = 0.88

    monkeypatch.setattr(adapter, "_refresh_detection_outputs", fake_refresh)

    result = adapter.detect_latest()

    assert refresh_calls["count"] == 1
    assert result.ok is True
    assert len(result.detections) == 1
    assert result.detections[0].confidence == 0.88
    assert result.detections[0].center_x == 5.0
    assert result.detections[0].center_y == 3.0


def test_stream_camera_emits_multipart_jpeg_frame() -> None:
    adapter = MockCameraVisionAdapter()

    async def consume_first_chunk() -> bytes:
        stream = adapter.stream_camera()
        try:
            return await anext(stream)
        finally:
            await stream.aclose()

    chunk = asyncio.run(consume_first_chunk())
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
    assert b"\xff\xd8" in chunk


def test_detect_latest_uses_expected_mock_points() -> None:
    adapter = MockCameraVisionAdapter(frame_width=1920, frame_height=1080)

    result = adapter.detect_latest()

    assert result.ok is True
    assert len(result.detections) == 1
    corners = [
        (int(corner.x), int(corner.y)) for corner in result.detections[0].corners
    ]
    assert corners == [(920, 434), (1162, 438), (1160, 754), (919, 753)]
