from pathlib import Path

from app.adapters.camera import CameraAdapter
from app.adapters.dms import DmsAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.adapters.vision import VisionAdapter
from app.services.orchestrator import OrchestratorService


def test_create_job_creates_job(tmp_path: Path) -> None:
    svc = OrchestratorService(
        camera=CameraAdapter(),
        vision=VisionAdapter(),
        robot=RobotAdapter(),
        dms=DmsAdapter(base_url="http://localhost:8080"),
        storage=StorageAdapter(base_dir=str(tmp_path)),
    )
    job = svc.create_job(options={"foo": "bar"}, path="path-1")
    assert job.id
    assert job.options == {"foo": "bar"}
    assert job.path == "path-1"
