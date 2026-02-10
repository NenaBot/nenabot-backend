from __future__ import annotations

from typing import Optional

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.dms import DmsAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService


def create_orchestrator(
    storage_dir: str = "data",
    dms_base_url: str = "http://localhost:8080"
) -> OrchestratorService:
    """Factory function to create an OrchestratorService with default dependencies."""
    return OrchestratorService(
        camera_vision=CameraVisionAdapter(),
        robot=RobotAdapter(),
        dms=DmsAdapter(base_url=dms_base_url),
        storage=StorageAdapter(base_dir=storage_dir),
    )


_default_orchestrator: Optional[OrchestratorService] = None


def get_orchestrator() -> OrchestratorService:
    """
    Dependency injection function for FastAPI.
    Returns the global orchestrator instance, creating it if necessary.
    Can be overridden in tests by using app.dependency_overrides.
    """
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = create_orchestrator()
    return _default_orchestrator
