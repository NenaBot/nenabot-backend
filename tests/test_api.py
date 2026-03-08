import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import create_orchestrator, get_orchestrator
from app.domain.models import Waypoint
from app.main import app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with an isolated orchestrator.

    Uses an in-memory SQLite database.
    Pre-populates calibration state so job creation works.
    """
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
    response = client.get("/health")
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

    response = client.get("/status")
    assert response.status_code == 200
    assert response.json()["state"] in {"ready", "busy", "error"}


def test_jobs_lifecycle(client: TestClient) -> None:
    # Pixel coords — backend converts to robot mm using calibration
    # Calibration: robot_start=(100,200), canvas_start=(640,400), ppm=2
    path = [{"x": 650.0, "y": 390.0}, {"x": 660.0, "y": 380.0}]
    response = client.post("/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0})
    assert response.status_code == 201
    job = response.json()
    job_id = job["id"]
    assert job["status"]["state"] in ("created", "running", "completed")
    assert job["dryRun"] is True
    # path includes starting point prepended + 2 waypoints = 3
    assert len(job["path"]) == 3

    # Wait for dry-run to finish (should be fast)
    for _ in range(20):
        resp = client.get(f"/jobs/{job_id}")
        if resp.json()["status"]["state"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.1)

    final = client.get(f"/jobs/{job_id}").json()
    assert final["status"]["state"] == "completed"
    assert final["status"]["lastPointProcessed"] == 3  # start + 2 waypoints
    assert len(final["measurements"]) == 3
    assert final["measurements"][0]["simulated"] is True

    response = client.get("/jobs")
    assert response.status_code == 200
    assert any(j["id"] == job_id for j in response.json())

    response = client.get("/jobs/latest")
    assert response.status_code == 200
    assert response.json()["id"] == job_id

    response = client.delete(f"/jobs/{job_id}")
    assert response.status_code == 204


def test_dry_run_job_measurements(client: TestClient) -> None:
    """Dry run should produce simulated measurements with correct waypoints."""
    # Pixel coords: the backend will convert these + prepend starting point
    path = [
        {"x": 640, "y": 400},  # same as canvas start → robot start
        {"x": 660, "y": 400},  # 20px right → robot y decreases by 10mm
        {"x": 640, "y": 380},  # 20px up → robot x increases by 10mm
    ]
    res = client.post("/jobs", json={"path": path, "dryRun": True, "workZ": 5, "workR": 0})
    assert res.status_code == 201
    job_id = res.json()["id"]

    # Poll until done
    for _ in range(30):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"]["state"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert job["status"]["state"] == "completed"
    # 1 starting point + 3 waypoints = 4
    assert job["status"]["lastPointProcessed"] == 4
    for m in job["measurements"]:
        assert m["simulated"] is True
        assert m["timestamp"]  # non-empty


def test_stop_job(client: TestClient) -> None:
    """Stopping a running job should set state to stopped."""
    # Use many pixel waypoints so the job is still running when we stop it
    path = [{"x": float(i), "y": float(i)} for i in range(50)]
    res = client.post("/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0})
    job_id = res.json()["id"]
    time.sleep(0.2)  # let it process a few

    stop_res = client.post("/robot/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["stopped"] is True

    # Wait for thread to finish
    for _ in range(20):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"]["state"] in ("stopped", "completed"):
            break
        time.sleep(0.1)

    assert job["status"]["state"] == "stopped"
    # Should have processed fewer than 51 (50 waypoints + 1 start)
    assert job["status"]["lastPointProcessed"] < 51


def test_profiles_and_paths(client: TestClient) -> None:
    response = client.get("/profiles")
    assert response.status_code == 200
    assert response.json()

    response = client.get("/profiles/default")
    assert response.status_code == 200
    assert response.json()["name"]

    response = client.post("/paths", json={"options": {"speed": 1}})
    assert response.status_code == 201
    body = response.json()
    assert "ok" in body
    assert "detections" in body
    assert isinstance(body["detections"], list)


def test_job_image_endpoint(client: TestClient) -> None:
    """GET /jobs/{id}/image returns 404 when no image is stored."""
    path = [{"x": 1, "y": 2}]
    res = client.post("/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0})
    job_id = res.json()["id"]

    # Image endpoint should return 404 if no image was attached
    img_res = client.get(f"/jobs/{job_id}/image")
    assert img_res.status_code == 404


def test_job_persists_across_reads(client: TestClient) -> None:
    """Jobs should survive re-reads from DB after completion."""
    path = [{"x": 650, "y": 390}, {"x": 660, "y": 380}]
    res = client.post("/jobs", json={"path": path, "dryRun": True, "workZ": 0, "workR": 0})
    job_id = res.json()["id"]

    for _ in range(30):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"]["state"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    # Re-fetch from DB
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"]["state"] == "completed"
    # 1 starting point + 2 waypoints = 3 measurements
    assert len(job["measurements"]) == 3
