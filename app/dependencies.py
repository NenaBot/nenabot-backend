from __future__ import annotations

from typing import Optional

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.database import Database
from app.adapters.ionVision.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService


def create_orchestrator(
    db_path: str = "data/nenabot.db",
    dms_base_url: str = "http://localhost:8080",
) -> OrchestratorService:
    """Factory function to create an OrchestratorService with default dependencies."""
    db = Database(db_path=db_path)
    db.init_db()
    return OrchestratorService(
        camera_vision=CameraVisionAdapter(),
        robot=RobotAdapter(),
        dms=IVAdapter(base_url=dms_base_url),
        storage=StorageAdapter(db=db),
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
