import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.camera_vision import (
    CaptureResult,
    Corner,
    DetectionResults,
    MarkerCorners,
)
from app.adapters.robot import PoseResult, RobotResult
from app.dependencies import create_orchestrator, get_orchestrator
from app.domain.models import Waypoint
from app.main import app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with an isolated orchestrator.

    Uses an in-memory SQLite database.
    Pre-populates calibration state so job creation works.
    Hardware adapters are mocked so tests never access real devices.
    """
    with patch(
        "app.adapters.camera_vision.CameraVisionAdapter.ping",
        return_value=CaptureResult(ok=False, error="no camera in test"),
    ), patch(
        "app.adapters.camera_vision.CameraVisionAdapter.capture",
        return_value=CaptureResult(ok=True, image_path="/tmp/fake_capture.jpg"),
    ), patch(
        "app.adapters.camera_vision.CameraVisionAdapter.detect",
        return_value=DetectionResults(ok=True, detections=[]),
    ), patch(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ), patch(
        "app.adapters.robot.RobotAdapter.ping",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ):
        test_orchestrator = create_orchestrator(
            db_path=str(tmp_path / "test.db"),
            dms_base_url="http://localhost:8080",
        )

        # Pre-populate calibration state (normally set by POST /paths)
        # This represents: robot at (100, 200, 0, 0) mm, canvas start at (640, 400) px,
        # with a scale of 2 pixels per mm.
        test_orchestrator._cal_robot_start = Waypoint(x=100.0, y=200.0, z=0.0, r=0.0)
        test_orchestrator._cal_canvas_start = (640.0, 400.0)
        test_orchestrator._cal_pixels_per_mm = 2.0

        app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

        with TestClient(app) as test_client:
            yield test_client

        app.dependency_overrides.clear()


def test_health_and_status(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "ok"
    assert "camera" in health
    assert "dms" in health
    assert "robot" in health
    assert "uptimeSeconds" in health
    assert health["uptimeSeconds"] >= 0
    # Each component should report a status and optional error
    for key in ("camera", "dms", "robot"):
        assert "status" in health[key]
        assert health[key]["status"] in {"connected", "disconnected", "error"}

    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["state"] in {"ready", "busy", "error"}


def test_jobs_lifecycle(client: TestClient) -> None:
    # Pixel coords — backend converts to robot mm using calibration
    # Calibration: robot_start=(100,200), canvas_start=(640,400), ppm=2
    path = [{"x": 650.0, "y": 390.0}, {"x": 660.0, "y": 380.0}]
    response = client.post(
        "/api/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0}
    )
    assert response.status_code == 201
    job = response.json()
    job_id = job["id"]
    assert job["status"]["state"] in ("created", "running", "completed")
    assert job["dryRun"] is True
    # path contains only the 2 measurement waypoints (starting point stored separately)
    assert len(job["path"]) == 2

    # Wait for dry-run to finish (should be fast)
    for _ in range(20):
        resp = client.get(f"/api/jobs/{job_id}")
        if resp.json()["status"]["state"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.1)

    final = client.get(f"/api/jobs/{job_id}").json()
    assert final["status"]["state"] == "completed"
    assert final["status"]["lastPointProcessed"] == 2
    assert len(final["measurements"]) == 2
    assert final["measurements"][0]["simulated"] is True

    response = client.get("/api/jobs")
    assert response.status_code == 200
    assert any(j["id"] == job_id for j in response.json())

    response = client.get("/api/jobs/latest")
    assert response.status_code == 200
    assert response.json()["id"] == job_id

    response = client.delete(f"/api/jobs/{job_id}")
    assert response.status_code == 204


def test_dry_run_job_measurements(client: TestClient) -> None:
    """Dry run should produce simulated measurements with correct waypoints."""
    # Pixel coords: the backend will convert these + prepend starting point
    path = [
        {"x": 640, "y": 400},  # same as canvas start → robot start
        {"x": 660, "y": 400},  # 20px right → robot y decreases by 10mm
        {"x": 640, "y": 380},  # 20px up → robot x increases by 10mm
    ]
    res = client.post(
        "/api/jobs", json={"path": path, "dryRun": True, "workZ": 5, "workR": 0}
    )
    assert res.status_code == 201
    job_id = res.json()["id"]

    # Poll until done
    for _ in range(30):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"]["state"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert job["status"]["state"] == "completed"
    # 3 measurement waypoints (starting point not included)
    assert job["status"]["lastPointProcessed"] == 3
    for m in job["measurements"]:
        assert m["simulated"] is True
        assert m["timestamp"]  # non-empty


def test_stop_job(client: TestClient) -> None:
    """Stopping a running job should set state to stopped."""
    # Use many pixel waypoints so the job is still running when we stop it
    path = [{"x": float(i), "y": float(i)} for i in range(50)]
    res = client.post(
        "/api/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0}
    )
    job_id = res.json()["id"]
    time.sleep(0.2)  # let it process a few

    stop_res = client.post("/api/robot/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["stopped"] is True

    # Wait for thread to finish
    for _ in range(20):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"]["state"] in ("stopped", "completed"):
            break
        time.sleep(0.1)

    assert job["status"]["state"] == "stopped"
    # Should have processed fewer than 51 (50 waypoints + 1 start)
    assert job["status"]["lastPointProcessed"] < 51


def test_profiles_and_paths(client: TestClient) -> None:
    response = client.get("/api/profiles")
    assert response.status_code == 200
    assert response.json()

    response = client.get("/api/profiles/default")
    assert response.status_code == 200
    assert response.json()["name"]

    response = client.post("/api/paths", json={"options": {"speed": 1}})
    assert response.status_code == 201
    body = response.json()
    assert "requestSucceeded" in body
    assert "detections" in body
    assert isinstance(body["detections"], list)


def test_paths_returns_ok_when_detection_is_empty_but_calibration_succeeds(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"fake-jpeg")
    marker = MarkerCorners(
        corners=[
            Corner(x=10.0, y=10.0),
            Corner(x=20.0, y=10.0),
            Corner(x=20.0, y=20.0),
            Corner(x=10.0, y=20.0),
        ]
    )

    with patch(
        "app.adapters.camera_vision.CameraVisionAdapter.ping",
        return_value=CaptureResult(ok=False, error="no camera in test"),
    ), patch(
        "app.adapters.camera_vision.CameraVisionAdapter.capture",
        return_value=CaptureResult(ok=True, image_path=str(image_path)),
    ), patch(
        "app.adapters.camera_vision.CameraVisionAdapter.detect",
        return_value=DetectionResults(
            ok=False,
            detections=[],
            pixels_per_mm=2.0,
            marker_count=1,
            marker_corners=[marker],
            error="No battery contour detected",
        ),
    ), patch(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ), patch(
        "app.adapters.robot.RobotAdapter.ping",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ), patch(
        "app.adapters.robot.RobotAdapter.get_pose",
        return_value=PoseResult(ok=True, x=100.0, y=200.0, z=0.0, r=0.0),
    ):
        test_orchestrator = create_orchestrator(
            db_path=str(tmp_path / "test_paths_ok.db"),
            dms_base_url="http://localhost:8080",
        )
        app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

        with TestClient(app) as client:
            response = client.post("/api/paths", json={"options": {}})

        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["requestSucceeded"] is True
    assert body["detections"] == []
    assert body["markerCount"] == 1
    assert body["calibration"]["calibrated"] is True
    assert body["calibration"]["robotStart"]["x"] == pytest.approx(100.0)
    assert "No battery contour detected" in body["error"]


def test_job_image_endpoint(client: TestClient) -> None:
    """GET /jobs/{id}/image returns 404 when no image is stored."""
    path = [{"x": 1, "y": 2}]
    res = client.post(
        "/api/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0}
    )
    job_id = res.json()["id"]

    # Image endpoint should return 404 if no image was attached
    img_res = client.get(f"/api/jobs/{job_id}/image")
    assert img_res.status_code == 404


def test_job_persists_across_reads(client: TestClient) -> None:
    """Jobs should survive re-reads from DB after completion."""
    path = [{"x": 650, "y": 390}, {"x": 660, "y": 380}]
    res = client.post(
        "/api/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0}
    )
    job_id = res.json()["id"]

    for _ in range(30):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"]["state"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    # Re-fetch from DB
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"]["state"] == "completed"


def test_job_creation_requires_calibration(tmp_path: Path) -> None:
    """POST /jobs should return 409 when the orchestrator is not calibrated."""
    with patch(
        "app.adapters.camera_vision.CameraVisionAdapter.ping",
        return_value=CaptureResult(ok=False, error="no camera in test"),
    ), patch(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ), patch(
        "app.adapters.robot.RobotAdapter.ping",
        return_value=RobotResult(ok=False, error="no robot in test"),
    ):
        test_orchestrator = create_orchestrator(
            db_path=str(tmp_path / "test_nocal.db"),
            dms_base_url="http://localhost:8080",
        )
        # Deliberately NOT setting calibration state

        app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

        with TestClient(app) as uncalibrated_client:
            path = [{"x": 1.0, "y": 2.0}]
            response = uncalibrated_client.post(
                "/api/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0}
            )
            assert response.status_code == 409
            assert "calibrat" in response.json()["detail"].lower()

        app.dependency_overrides.clear()


def test_job_sse_events(client: TestClient) -> None:
    """SSE endpoint should stream job progress events for a dry-run job."""
    path = [{"x": 650, "y": 390}, {"x": 660, "y": 380}]
    res = client.post(
        "/api/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0}
    )
    assert res.status_code == 201
    job_id = res.json()["id"]

    # Connect to SSE stream
    import json as _json

    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(_json.loads(line[len("data: ") :]))
                # Stop after terminal event
                if events[-1].get("state") in ("completed", "failed", "stopped"):
                    break

    # First event should be snapshot
    assert events[0]["type"] == "job:snapshot"
    assert events[0]["jobId"] == job_id

    # Last event should be completed
    assert events[-1]["state"] == "completed"

    # Should contain waypoint_completed events
    wp_completed = [e for e in events if e["type"] == "job:waypoint_completed"]
    assert len(wp_completed) >= 1
    assert wp_completed[0].get("measurement") is not None
