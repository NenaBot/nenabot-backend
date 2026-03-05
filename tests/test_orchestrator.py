from pathlib import Path

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService


def test_create_job_creates_job(tmp_path: Path) -> None:
    svc = OrchestratorService(
        camera_vision=CameraVisionAdapter(),
        robot=RobotAdapter(),
        dms=IVAdapter(base_url="http://localhost:8080",ws_base_url="ws://localhost:8080"),
        storage=StorageAdapter(base_dir=str(tmp_path)),
    )
    job = svc.create_job(options={"foo": "bar"}, path="path-1")
    assert job.id
    assert job.options == {"foo": "bar"}
    assert job.path == "path-1"
