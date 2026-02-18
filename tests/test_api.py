import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import create_orchestrator, get_orchestrator


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with an isolated orchestrator instance (in-memory SQLite)."""
    test_orchestrator = create_orchestrator(
        db_path=str(tmp_path / "test.db"),
        dms_base_url="http://localhost:8080",
    )

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

    response = client.get("/status")
    assert response.status_code == 200
    assert response.json()["state"] in {"ready", "busy", "error"}


def test_jobs_lifecycle(client: TestClient) -> None:
    path = [{"x": 1.0, "y": 2.0, "z": 0, "r": 0}, {"x": 3.0, "y": 4.0}]
    response = client.post("/jobs", json={"path": path, "dryRun": True})
    assert response.status_code == 201
    job = response.json()
    job_id = job["id"]
    assert job["status"]["state"] in ("created", "running", "completed")
    assert job["dryRun"] is True
    assert len(job["path"]) == 2

    # Wait for dry-run to finish (should be fast)
    for _ in range(20):
        resp = client.get(f"/jobs/{job_id}")
        if resp.json()["status"]["state"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.1)

    final = client.get(f"/jobs/{job_id}").json()
    assert final["status"]["state"] == "completed"
    assert final["status"]["lastPointProcessed"] == 2
    assert len(final["measurements"]) == 2
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
    path = [
        {"x": 10, "y": 20, "z": 5, "r": 0},
        {"x": 30, "y": 40, "z": 5, "r": 90},
        {"x": 50, "y": 60, "z": 5, "r": 0},
    ]
    res = client.post("/jobs", json={"path": path, "dryRun": True})
    assert res.status_code == 201
    job_id = res.json()["id"]

    # Poll until done
    for _ in range(30):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"]["state"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert job["status"]["state"] == "completed"
    assert job["status"]["lastPointProcessed"] == 3
    for i, m in enumerate(job["measurements"]):
        assert m["waypointIndex"] == i
        assert m["simulated"] is True
        assert m["waypoint"]["x"] == path[i]["x"]
        assert m["waypoint"]["y"] == path[i]["y"]
        assert m["timestamp"]  # non-empty


def test_stop_job(client: TestClient) -> None:
    """Stopping a running job should set state to stopped."""
    # Use many waypoints so the job is still running when we stop it
    path = [{"x": float(i), "y": float(i)} for i in range(50)]
    res = client.post("/jobs", json={"path": path, "dryRun": True})
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
    # Should have processed fewer than 50
    assert job["status"]["lastPointProcessed"] < 50


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
    res = client.post("/jobs", json={"path": path, "dryRun": True})
    job_id = res.json()["id"]

    # Image endpoint should return 404 if no image was attached
    img_res = client.get(f"/jobs/{job_id}/image")
    assert img_res.status_code == 404


def test_job_persists_across_reads(client: TestClient) -> None:
    """Jobs should survive re-reads from DB after completion."""
    path = [{"x": 5, "y": 10}, {"x": 15, "y": 20}]
    res = client.post("/jobs", json={"path": path, "dryRun": True})
    job_id = res.json()["id"]

    for _ in range(30):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"]["state"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    # Re-fetch from DB
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"]["state"] == "completed"
    assert len(job["measurements"]) == 2
    assert job["measurements"][0]["waypoint"]["x"] == 5
    assert job["measurements"][1]["waypoint"]["x"] == 15
