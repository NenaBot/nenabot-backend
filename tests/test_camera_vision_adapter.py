import asyncio
from unittest.mock import MagicMock

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


def test_stream_camera_offloads_worker_bound_steps(monkeypatch) -> None:
    adapter = CameraVisionAdapter()
    threaded_calls: list[str] = []

    def ensure_capture_running() -> CaptureResult:
        return CaptureResult(ok=True)

    def camera_stream_chunk() -> bytes:
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


def test_stream_detection_offloads_worker_bound_steps(monkeypatch) -> None:
    adapter = CameraVisionAdapter()
    threaded_calls: list[str] = []

    def ensure_capture_running() -> CaptureResult:
        return CaptureResult(ok=True)

    def detection_stream_chunk() -> bytes:
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
