from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.adapters.camera_vision import (
    CaptureResult,
    Corner,
    DetectionResult,
    DetectionResults,
)
from app.adapters.database import Database
from app.adapters.ionVision import IVResult
from app.adapters.robot import PoseResult, RobotResult
from app.adapters.storage import StorageAdapter
from app.dependencies import get_orchestrator
from app.domain.models import Waypoint
from app.main import app
from app.services.orchestrator import OrchestratorService

pytestmark = [pytest.mark.ionvision]


class FakeCameraVisionAdapter:
    def __init__(self, capture_path: Path) -> None:
        self._capture_path = capture_path
        self.capture_calls = 0
        self.detect_calls = 0
        self.intrinsics_loaded = True

    def ping(self) -> CaptureResult:
        return CaptureResult(ok=True)

    def checkerboard_status(self) -> dict[str, bool | str | None]:
        return {"visible": True, "error": None}

    def checkerboard_visible(self) -> bool:
        return True

    def capture(self) -> CaptureResult:
        self.capture_calls += 1
        return CaptureResult(ok=True, image_path=str(self._capture_path))

    def detect_latest(self) -> DetectionResults:
        self.detect_calls += 1

        return DetectionResults(
            ok=True,
            detections=[
                DetectionResult(
                    corners=[
                        Corner(x=10.0, y=10.0),
                        Corner(x=20.0, y=10.0),
                        Corner(x=20.0, y=20.0),
                        Corner(x=10.0, y=20.0),
                    ],
                    width_mm=10.0,
                    height_mm=10.0,
                    center_x=15.0,
                    center_y=15.0,
                    confidence=0.99,
                )
            ],
            image_base64="ZmFrZS1pbWFnZQ==",
        )


class FakeRobotAdapter:
    def __init__(self) -> None:
        self.move_calls: list[tuple[float, float, float, float]] = []
        self.wait_calls: list[tuple[float, float, float, float]] = []

    def ping(self) -> RobotResult:
        return RobotResult(ok=True)

    def get_pose(self) -> PoseResult:
        return PoseResult(ok=True, x=100.0, y=200.0, z=0.0, r=0.0)

    def move(
        self,
        x: float,
        y: float,
        z: float,
        r: float,
        wait: bool = True,
    ) -> RobotResult:
        self.move_calls.append((x, y, z, r))
        return RobotResult(ok=True)

    def wait_for_position(
        self,
        x: float,
        y: float,
        z: float,
        r: float,
        **_: object,
    ) -> PoseResult:
        self.wait_calls.append((x, y, z, r))
        return PoseResult(ok=True, x=x, y=y, z=z, r=r)

    def stop(self) -> RobotResult:
        return RobotResult(ok=True)


class FakeIonVisionAdapter:
    def __init__(self) -> None:
        self.ping_calls = 0
        self.start_new_scan_calls = 0
        self.get_current_scan_calls = 0
        self.get_latest_dataobject_calls = 0

    def ping(self) -> IVResult:
        self.ping_calls += 1
        return IVResult(ok=True, payload={"id": "preset-1"})

    async def initialize_websocket(self) -> None:
        return None

    async def disconnect_websocket(self) -> None:
        return None

    def on_event(self, event_type: str, handler) -> None:
        return None

    def off_event(self, event_type: str, handler) -> None:
        return None

    def start_new_scan(self) -> IVResult:
        self.start_new_scan_calls += 1
        return IVResult(ok=True, payload={"message": "scan started"})

    def get_current_scan(self) -> IVResult:
        self.get_current_scan_calls += 1
        if self.get_current_scan_calls == 1:
            return IVResult(ok=True, payload={"state": "running", "progress": 50})
        return IVResult(ok=True, payload={"state": "finished", "progress": 100})

    def get_latest_dataobject(self) -> IVResult:
        self.get_latest_dataobject_calls += 1
        return IVResult(
            ok=True,
            payload={
                "id": "result-123",
                "scanName": "mock-ionvision-scan",
                "gasDetection": {"gasName": "ethanol", "confidence": 0.93},
            },
        )


@pytest.fixture
def ionvision_client(tmp_path: Path):
    capture_path = tmp_path / "capture.jpg"
    capture_path.write_bytes(b"fake-jpeg-bytes")

    db = Database(db_path=str(tmp_path / "nenabot.db"))
    db.init_db()

    fake_camera = FakeCameraVisionAdapter(capture_path)
    fake_robot = FakeRobotAdapter()
    fake_dms = FakeIonVisionAdapter()
    orchestrator = OrchestratorService(
        camera_vision=fake_camera,
        robot=fake_robot,
        ionvision=fake_dms,
        storage=StorageAdapter(db=db),
    )
    orchestrator._mapping_data = {
        "start_pose": {"x": 200.0, "y": 200.0, "z": 0.0, "r": 0.0}
    }
    orchestrator.pixel_to_robot = lambda _px, _py, work_z, work_r: Waypoint(
        x=200.0,
        y=200.0,
        z=work_z,
        r=work_r,
    )

    with patch("app.main.get_orchestrator", return_value=orchestrator), patch(
        "app.services.orchestrator.time.sleep",
        side_effect=lambda *_args, **_kwargs: None,
    ):
        app.dependency_overrides[get_orchestrator] = lambda: orchestrator
        with TestClient(app) as client:
            yield client, fake_dms, fake_camera, fake_robot
        app.dependency_overrides.clear()


def _wait_for_job_completion(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    while True:
        response = client.get(f"/api/job/{job_id}")
        assert response.status_code == 200
        job = response.json()
        state = job["status"]["state"]
        if state in {"completed", "failed", "stopped"}:
            return job
        if time.monotonic() >= deadline:
            raise AssertionError(f"job {job_id} did not finish in time: {state}")
        time.sleep(0.05)


def test_health_reports_mock_ionvision_connected(ionvision_client) -> None:
    client, fake_dms, _, _ = ionvision_client

    response = client.get("/api/health")

    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "ok"
    assert health["ionvision"]["status"] == "connected"
    assert fake_dms.ping_calls == 1


def test_non_dry_run_job_uses_mock_ionvision_scan_flow(ionvision_client) -> None:
    client, fake_dms, _, _ = ionvision_client

    detect_response = client.post("/api/path/detect", json={"options": {}})
    assert detect_response.status_code == 201
    detect_payload = detect_response.json()
    assert detect_payload["requestSucceeded"] is True
    assert len(detect_payload["detections"]) == 1

    job_response = client.post(
        "/api/job",
        json={
            "path": [
                {"pixelX": 640.0, "pixelY": 400.0},
            ],
            "dryRun": False,
            "workZ": 0.0,
            "workR": 0.0,
        },
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    job = _wait_for_job_completion(client, job_id)

    assert job["status"]["state"] == "completed"
    assert job["status"]["lastPointProcessed"] == 1
    assert len(job["measurements"]) == 1
    assert job["measurements"][0]["simulated"] is False
    assert job["measurements"][0]["scanResult"]["id"] == "result-123"
    assert job["measurements"][0]["scanResult"]["gasDetection"]["gasName"] == "ethanol"
    assert fake_dms.start_new_scan_calls == 1
    assert fake_dms.get_current_scan_calls >= 2
    assert fake_dms.get_latest_dataobject_calls == 1
