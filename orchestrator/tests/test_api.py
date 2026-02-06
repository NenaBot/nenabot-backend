from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_start_and_get_job() -> None:
    response = client.post("/jobs/start", json={"packId": "PACK-1"})
    assert response.status_code == 200
    job_id = response.json()["id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == job_id
    assert payload["state"] == "running"
