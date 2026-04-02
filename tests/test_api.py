import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.adapters.camera_vision import (
    CaptureResult,
    CheckerboardResult,
    Corner,
    DetectionResult,
    DetectionResults,
)
from app.adapters.ionVision import IVResult
from app.adapters.robot import PoseResult, RobotResult
from app.dependencies import create_orchestrator, get_orchestrator
from app.main import app
from tests.calibration_helpers import (
    sample_correspondences,
    write_intrinsics,
    write_mapping,
)


def _make_bundle(tmp_path: Path, calibrated: bool) -> dict:
    intrinsics_path = write_intrinsics(tmp_path / "camera_intrinsics.json")
    mapping_path = tmp_path / "robot_mapping.json"
    if calibrated:
        write_mapping(mapping_path, intrinsics_path)

    with patch(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ), patch(
        "app.adapters.robot.RobotAdapter.ping",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ), patch(
        "app.adapters.ionVision.IVAdapter.ping",
        return_value=IVResult(ok=False, error="no dms in test"),
    ):
        service = create_orchestrator(
            db_path=str(tmp_path / "test.db"),
            dms_base_url="http://localhost:8080",
            intrinsics_path=str(intrinsics_path),
            mapping_path=str(mapping_path),
        )

    service.camera_vision.ping = MagicMock(
        return_value=CaptureResult(ok=False, error="no camera in test")
    )
    service.camera_vision.checkerboard_status = MagicMock(
        return_value={"visible": False, "error": "no camera in test"}
    )
    service.camera_vision.checkerboard_visible = MagicMock(return_value=False)
    service.camera_vision.detect_latest = MagicMock(
        return_value=DetectionResults(
            ok=False,
            detections=[],
            image_base64="ZmFrZS1pbWFnZQ==",
            error="No battery contour detected",
        )
    )
    service.camera_vision.get_latest_frame = MagicMock(
        return_value=np.zeros((720, 1280, 3), dtype=np.uint8)
    )
    service.camera_vision.frame_to_base64 = MagicMock(return_value="encoded-image")

    app.dependency_overrides[get_orchestrator] = lambda: service
    client = TestClient(app)
    return {
        "client": client,
        "service": service,
        "intrinsics_path": intrinsics_path,
        "mapping_path": mapping_path,
    }


@pytest.fixture
def calibrated_bundle(tmp_path: Path):
    bundle = _make_bundle(tmp_path, calibrated=True)
    with bundle["client"] as client:
        bundle["client"] = client
        yield bundle
    app.dependency_overrides.clear()


@pytest.fixture
def uncalibrated_bundle(tmp_path: Path):
    bundle = _make_bundle(tmp_path, calibrated=False)
    with bundle["client"] as client:
        bundle["client"] = client
        yield bundle
    app.dependency_overrides.clear()


def test_health_and_status(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]

    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert "camera" in body
    assert "dms" in body
    assert "robot" in body

    status = client.get("/api/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["state"] == "ready"
    assert payload["calibration"]["intrinsicsLoaded"] is True
    assert payload["calibration"]["calibrated"] is True
    assert payload["calibration"]["lastCalibratedAt"] == "2026-04-02T10:00:00+00:00"


def test_jobs_lifecycle(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]
    path = [
        {"pixelX": 150.0, "pixelY": 150.0},
        {"pixelX": 175.0, "pixelY": 175.0},
    ]
    response = client.post(
        "/api/job",
        json={"path": path, "dryRun": True, "workZ": 0, "workR": 0},
    )
    assert response.status_code == 201
    job = response.json()
    job_id = job["id"]

    for _ in range(20):
        latest = client.get(f"/api/job/{job_id}").json()
        if latest["status"]["state"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.1)

    latest = client.get(f"/api/job/{job_id}").json()
    assert latest["status"]["state"] == "completed"
    assert latest["status"]["lastPointProcessed"] == 2
    assert len(latest["measurements"]) == 2


def test_path_detect_returns_detection_payload(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]
    service = calibrated_bundle["service"]

    service.camera_vision.detect_latest = MagicMock(
        return_value=DetectionResults(
            ok=True,
            detections=[
                DetectionResult(
                    corners=[
                        Corner(x=100.0, y=100.0),
                        Corner(x=200.0, y=100.0),
                        Corner(x=200.0, y=200.0),
                        Corner(x=100.0, y=200.0),
                    ],
                    width_mm=80.0,
                    height_mm=40.0,
                    center_x=150.0,
                    center_y=150.0,
                    confidence=0.8,
                )
            ],
            image_base64="ZmFrZS1pbWFnZQ==",
            error=None,
        )
    )

    response = client.post("/api/path/detect", json={"options": {}})
    assert response.status_code == 201
    payload = response.json()
    assert payload["requestSucceeded"] is True
    assert len(payload["detections"]) == 1
    assert "calibration" not in payload
    assert payload["image_base64"] == "ZmFrZS1pbWFnZQ=="


def test_job_creation_requires_calibration(uncalibrated_bundle) -> None:
    client = uncalibrated_bundle["client"]
    response = client.post(
        "/api/job",
        json={
            "path": [{"pixelX": 1.0, "pixelY": 2.0}],
            "dryRun": True,
            "workZ": 0,
            "workR": 0,
        },
    )
    assert response.status_code == 409
    assert "calibrat" in response.json()["detail"].lower()


def test_real_job_creation_requires_ready_robot(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]
    service = calibrated_bundle["service"]
    service._robot.ping = MagicMock(
        return_value=RobotResult(ok=False, error="robot offline")
    )

    response = client.post(
        "/api/job",
        json={
            "path": [{"pixelX": 150.0, "pixelY": 150.0}],
            "dryRun": False,
            "workZ": -48,
            "workR": 0,
        },
    )

    assert response.status_code == 409
    assert "robot not ready" in response.json()["detail"].lower()


def test_real_job_creation_rejects_unreachable_waypoints(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]
    service = calibrated_bundle["service"]
    service._robot.ping = MagicMock(return_value=RobotResult(ok=True))

    response = client.post(
        "/api/job",
        json={
            "path": [{"pixelX": 1.0, "pixelY": 1.0}],
            "dryRun": False,
            "workZ": -48,
            "workR": 0,
        },
    )

    assert response.status_code == 409
    assert "working radius" in response.json()["detail"].lower()


def test_calibration_flow_endpoint_writes_mapping_and_updates_status(
    uncalibrated_bundle,
) -> None:
    client = uncalibrated_bundle["client"]
    service = uncalibrated_bundle["service"]
    mapping_path = uncalibrated_bundle["mapping_path"]

    image_points, robot_points = sample_correspondences()
    service.camera_vision.find_checkerboard = MagicMock(
        return_value=CheckerboardResult(
            ok=True,
            corners=[Corner(x=x, y=y) for x, y in image_points],
            target_points=[Corner(x=x, y=y) for x, y in image_points],
            image_size=(1280, 720),
        )
    )
    service.camera_vision.checkerboard_status = MagicMock(
        return_value={"visible": True, "error": None}
    )
    service.camera_vision.checkerboard_visible = MagicMock(return_value=True)

    start_pose = PoseResult(ok=True, x=10.0, y=20.0, z=30.0, r=40.0)
    captured_poses = [
        PoseResult(ok=True, x=x, y=y, z=z, r=0.0) for x, y, z in robot_points
    ]
    service._robot.get_pose = MagicMock(side_effect=[start_pose, *captured_poses])

    start = client.post("/api/calibration", json={"action": "start"})
    assert start.status_code == 200
    start_payload = start.json()
    assert start_payload["ok"] is True
    assert start_payload["referenceImageBase64"] == "encoded-image"
    assert start_payload["targetPoint"]["pixelX"] == 100.0
    assert start_payload["targetPoint"]["pixelY"] == 100.0
    assert start_payload["targetPoint"]["gridRow"] == 4
    assert start_payload["targetPoint"]["gridCol"] == 0
    assert start_payload["targetPoint"]["step"] == 1
    assert start_payload["targetPoint"]["label"] == "P1 (4,0)"

    for expected_step in range(1, 5):
        response = client.post("/api/calibration", json={"action": "capture"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["currentStep"] == expected_step

    assert mapping_path.exists()
    saved = json.loads(mapping_path.read_text())
    assert saved["plane"]["origin"] == pytest.approx([200.0, 200.0, -50.0])
    status = client.get("/api/status").json()
    assert status["calibration"]["calibrated"] is True
    assert status["calibration"]["lastCalibratedAt"] is not None


def test_job_sse_events(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]

    response = client.post(
        "/api/job",
        json={
            "path": [
                {"pixelX": 150.0, "pixelY": 150.0},
                {"pixelX": 175.0, "pixelY": 175.0},
            ],
            "dryRun": True,
            "workZ": 0,
            "workR": 0,
        },
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    import json as _json

    with client.stream("GET", f"/api/job/{job_id}/events") as stream_response:
        assert stream_response.status_code == 200
        assert "text/event-stream" in stream_response.headers["content-type"]

        events = []
        for line in stream_response.iter_lines():
            if line.startswith("data: "):
                events.append(_json.loads(line[len("data: ") :]))
                if events[-1].get("state") in ("completed", "failed", "stopped"):
                    break

    assert events[0]["type"] == "job:snapshot"
    assert events[-1]["state"] == "completed"
    assert any(event["type"] == "job:waypoint_completed" for event in events)


def test_path_populate_requires_calibration(uncalibrated_bundle) -> None:
    client = uncalibrated_bundle["client"]
    response = client.post(
        "/api/path/populate",
        json={
            "measuringPointsPerCm": 1.0,
            "batteries": [{"corners": [{"pixelX": 1.0, "pixelY": 2.0}]}],
        },
    )
    assert response.status_code == 409
    assert "calibrat" in response.json()["detail"].lower()


def test_path_populate_generates_perimeter_points(calibrated_bundle) -> None:
    client = calibrated_bundle["client"]
    response = client.post(
        "/api/path/populate",
        json={
            "measuringPointsPerCm": 0.5,
            "batteries": [
                {
                    "corners": [
                        {"pixelX": 100.0, "pixelY": 100.0},
                        {"pixelX": 200.0, "pixelY": 100.0},
                        {"pixelX": 200.0, "pixelY": 200.0},
                        {"pixelX": 100.0, "pixelY": 200.0},
                    ]
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"]
    assert payload["path"][0]["index"] == "0-0-0"
