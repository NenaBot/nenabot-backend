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


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_start_and_get_job(client: TestClient) -> None:
    response = client.post("/jobs/start", json={"packId": "PACK-1"})
    assert response.status_code == 200
    job_id = response.json()["id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == job_id
    assert payload["state"] == "running"
