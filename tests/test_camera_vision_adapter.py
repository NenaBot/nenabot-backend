import asyncio
from unittest.mock import MagicMock, patch

import numpy as np

from app.adapters.camera_vision import (
    CameraVisionAdapter,
    CaptureResult,
    CheckerboardResult,
)


def test_checkerboard_status_starts_capture_before_reading_frame() -> None:
    adapter = CameraVisionAdapter()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    adapter._ensure_capture_running = MagicMock(return_value=CaptureResult(ok=True))
    adapter.get_latest_frame = MagicMock(return_value=frame)
    adapter.find_checkerboard = MagicMock(return_value=CheckerboardResult(ok=True))

    status = adapter.checkerboard_status()

    adapter._ensure_capture_running.assert_called_once_with()
    adapter.get_latest_frame.assert_called_once_with(
        timeout_s=0.1,
        ensure_capture=False,
    )
    assert status == {"visible": True, "error": None}


def test_checkerboard_status_without_capture_start_is_non_intrusive() -> None:
    adapter = CameraVisionAdapter()

    adapter._ensure_capture_running = MagicMock(return_value=CaptureResult(ok=True))
    adapter.get_latest_frame = MagicMock(return_value=None)

    status = adapter.checkerboard_status(ensure_capture=False)

    adapter._ensure_capture_running.assert_not_called()
    adapter.get_latest_frame.assert_called_once_with(
        timeout_s=0.0,
        ensure_capture=False,
        touch_capture=False,
    )
    assert status == {"visible": False, "error": "Camera capture inactive"}


def test_non_intrusive_checkerboard_status_does_not_poison_cache() -> None:
    adapter = CameraVisionAdapter()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)

    adapter.get_latest_frame = MagicMock(return_value=None)
    adapter._capture_frame_for_processing = MagicMock(return_value=(frame, None))
    adapter.find_checkerboard = MagicMock(return_value=CheckerboardResult(ok=True))

    first = adapter.checkerboard_status(ensure_capture=False)
    second = adapter.checkerboard_status()

    adapter.get_latest_frame.assert_called_once_with(
        timeout_s=0.0,
        ensure_capture=False,
        touch_capture=False,
    )
    adapter._capture_frame_for_processing.assert_called_once_with(timeout_s=0.1)
    adapter.find_checkerboard.assert_called_once_with(frame)
    assert first == {"visible": False, "error": "Camera capture inactive"}
    assert second == {"visible": True, "error": None}


def test_close_keeps_thread_reference_until_capture_thread_stops() -> None:
    adapter = CameraVisionAdapter()
    fake_thread = MagicMock()
    fake_thread.is_alive.side_effect = [True, True, False, False]
    adapter._capture_thread = fake_thread
    adapter._capture_running = True
    adapter._capture_last_access = 123.0
    adapter._checkerboard_status_cache = {"visible": True, "error": None}
    adapter._checkerboard_status_cached_at = 456.0
    adapter._latest_frame = np.zeros((8, 8, 3), dtype=np.uint8)

    with patch("app.adapters.camera_vision.logger.warning") as warning:
        adapter.close(join_timeout_s=0.0)

    fake_thread.join.assert_called_once_with(timeout=0.0)
    warning.assert_called_once()
    assert adapter._capture_running is False
    assert adapter._capture_thread is fake_thread
    assert adapter._capture_alive() is False
    assert adapter._capture_last_access == 123.0
    assert adapter._checkerboard_status_cache == {"visible": True, "error": None}
    assert adapter._latest_frame is not None

    adapter.close(join_timeout_s=0.0)

    assert fake_thread.join.call_count == 1
    assert adapter._capture_thread is None
    assert adapter._capture_last_access == 0.0
    assert adapter._checkerboard_status_cache is None
    assert adapter._latest_frame is None


def test_stream_camera_offloads_worker_bound_steps(monkeypatch) -> None:
    adapter = CameraVisionAdapter()
    threaded_calls: list[str] = []
    active_stream_counts: list[int] = []

    def ensure_capture_running() -> CaptureResult:
        return CaptureResult(ok=True)

    def camera_stream_chunk() -> bytes:
        active_stream_counts.append(adapter.active_stream_count)
        return b"camera-frame"

    async def fake_to_thread(func, /, *args, **kwargs):
        threaded_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(adapter, "_ensure_capture_running", ensure_capture_running)
    monkeypatch.setattr(adapter, "_camera_stream_chunk", camera_stream_chunk)

    async def consume_first_chunk() -> bytes:
        stream = adapter.stream_camera()
        try:
            return await anext(stream)
        finally:
            await stream.aclose()

    assert asyncio.run(consume_first_chunk()) == b"camera-frame"
    assert threaded_calls == ["ensure_capture_running", "camera_stream_chunk"]
    assert active_stream_counts == [1]
    assert adapter.active_stream_count == 0


def test_stream_detection_offloads_worker_bound_steps(monkeypatch) -> None:
    adapter = CameraVisionAdapter()
    threaded_calls: list[str] = []
    active_stream_counts: list[int] = []

    def ensure_capture_running() -> CaptureResult:
        return CaptureResult(ok=True)

    def detection_stream_chunk() -> bytes:
        active_stream_counts.append(adapter.active_stream_count)
        return b"detection-frame"

    async def fake_to_thread(func, /, *args, **kwargs):
        threaded_calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(adapter, "_ensure_capture_running", ensure_capture_running)
    monkeypatch.setattr(adapter, "_detection_stream_chunk", detection_stream_chunk)

    async def consume_first_chunk() -> bytes:
        stream = adapter.stream_detection()
        try:
            return await anext(stream)
        finally:
            await stream.aclose()

    assert asyncio.run(consume_first_chunk()) == b"detection-frame"
    assert threaded_calls == ["ensure_capture_running", "detection_stream_chunk"]
    assert active_stream_counts == [1]
    assert adapter.active_stream_count == 0
