from __future__ import annotations

from app.adapters.camera import CameraAdapter
from app.adapters.dms import DmsAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.adapters.vision import VisionAdapter
from app.services.orchestrator import OrchestratorService

_orchestrator: OrchestratorService | None = None


def get_orchestrator() -> OrchestratorService:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OrchestratorService(
            camera=CameraAdapter(),
            vision=VisionAdapter(),
            robot=RobotAdapter(),
            dms=DmsAdapter(base_url="http://localhost:8080"),
            storage=StorageAdapter(),
        )
    return _orchestrator
