from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import create_orchestrator, get_orchestrator


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with an isolated orchestrator instance."""
    # Create orchestrator with temporary storage directory
    test_orchestrator = create_orchestrator(
        storage_dir=str(tmp_path),
        dms_base_url="http://localhost:8080"
    )

    # Override the dependency to use our test orchestrator
    app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

    with TestClient(app) as test_client:
        yield test_client

    # Clean up the override after the test
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
    response = client.post("/jobs", json={"options": {"foo": "bar"}, "path": "path-1"})
    assert response.status_code == 201
    job_id = response.json()["id"]

    response = client.get("/jobs")
    assert response.status_code == 200
    assert any(job["id"] == job_id for job in response.json())

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id

    response = client.get("/jobs/latest")
    assert response.status_code == 200
    assert response.json()["id"] == job_id

    response = client.delete(f"/jobs/{job_id}")
    assert response.status_code == 204


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
