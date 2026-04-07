from __future__ import annotations

import app.adapters.camera_vision as camera_vision


def test_detection_calibration_defaults_when_no_overrides(
    monkeypatch,
) -> None:
    monkeypatch.setattr(camera_vision, "DETECTION_CALIBRATION_OVERRIDES", {})

    adapter = camera_vision.CameraVisionAdapter(intrinsics_path=None)
    cfg = adapter._detection

    assert cfg.blur_kernel == 3
    assert cfg.canny_low == 50
    assert cfg.canny_high == 150
    assert cfg.dilate_kernel == 3
    assert cfg.dilate_iterations == 1
    assert cfg.area_min == 8000
    assert cfg.area_max == 150000
    assert cfg.approx_epsilon == 0.02
    assert cfg.vertices_min == 4
    assert cfg.vertices_max == 8
    assert cfg.aspect_min == 1.05
    assert cfg.aspect_max == 3.5
    assert cfg.max_mean_gray == 150


def test_detection_calibration_sanitizes_invalid_overrides(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        camera_vision,
        "DETECTION_CALIBRATION_OVERRIDES",
        {
            "blur_kernel": 2,
            "canny_low": 120,
            "canny_high": 100,
            "dilate_kernel": 0,
            "dilate_iterations": -2,
            "area_min": 15000,
            "area_max": 14000,
            "approx_epsilon": 0.0,
            "vertices_min": 2,
            "vertices_max": 1,
            "aspect_min": 0.0,
            "aspect_max": 0.0,
            "max_mean_gray": 500,
        },
    )

    adapter = camera_vision.CameraVisionAdapter(intrinsics_path=None)
    cfg = adapter._detection

    assert cfg.blur_kernel == 3
    assert cfg.canny_low == 120
    assert cfg.canny_high == 121
    assert cfg.dilate_kernel == 1
    assert cfg.dilate_iterations == 0
    assert cfg.area_min == 15000
    assert cfg.area_max == 15001
    assert cfg.approx_epsilon == 0.001
    assert cfg.vertices_min == 3
    assert cfg.vertices_max == 3
    assert cfg.aspect_min == 0.01
    assert cfg.aspect_max == 0.01
    assert cfg.max_mean_gray == 255
