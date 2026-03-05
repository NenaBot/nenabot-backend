from __future__ import annotations

import logging

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService

logger = logging.getLogger(__name__)


def create_orchestrator(
    db_path: str = "data/nenabot.db",
    dms_base_url: str = "http://localhost:8080",
    dms_ws_base_url: str = "ws://localhost:8080"
) -> OrchestratorService:
    """Create an OrchestratorService with default dependencies."""
    db = Database(db_path=db_path)
    db.init_db()

    robot = RobotAdapter()
    result = robot.connect_first_available()
    if result.ok:
        logger.info("Robot connected on startup")
    else:
        logger.warning("Robot not connected on startup: %s", result.error)

    return OrchestratorService(
        camera_vision=CameraVisionAdapter(),
        robot=robot,
        dms=IVAdapter(base_url=dms_base_url, ws_base_url=dms_ws_base_url),
        storage=StorageAdapter(db=db),
    )


_default_orchestrator: OrchestratorService | None = None


def get_orchestrator() -> OrchestratorService:
    """Return the global orchestrator instance (FastAPI dep).

    Creates the instance on first call.
    Can be overridden in tests via app.dependency_overrides.
    """
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = create_orchestrator()
    return _default_orchestrator
