from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit, urlunsplit

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService

logger = logging.getLogger(__name__)


def _first_env(*names: str) -> str | None:
    """Return the first non-empty environment variable from the given names."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _derive_ws_base_url(base_url: str) -> str:
    """Derive a WebSocket base URL from the configured HTTP base URL."""
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit(
        (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


def create_orchestrator(
    db_path: str = "data/nenabot.db",
    ionvision_base_url: str | None = None,
    ionvision_ws_base_url: str | None = None,
) -> OrchestratorService:
    """Create an OrchestratorService with default dependencies."""
    ionvision_base_url = (
        ionvision_base_url
        or _first_env("IONVISION_BASE_URL")
        or "http://localhost:8080"
    ).rstrip("/")
    ionvision_ws_base_url = (
        ionvision_ws_base_url
        or _first_env("IONVISION_WS_BASE_URL")
        or _derive_ws_base_url(ionvision_base_url)
    ).rstrip("/")

    max_jobs_raw = _first_env("NENABOT_MAX_JOBS")
    try:
        max_jobs = int(max_jobs_raw) if max_jobs_raw else 0
    except ValueError:
        logger.warning(
            "NENABOT_MAX_JOBS='%s' is not a valid integer — retention disabled",
            max_jobs_raw,
        )
        max_jobs = 0
    if max_jobs < 0:
        logger.warning(
            "NENABOT_MAX_JOBS='%s' must be non-negative — retention disabled",
            max_jobs_raw,
        )
        max_jobs = 0

    default_work_z_raw = _first_env("NENABOT_DEFAULT_WORK_Z")
    try:
        default_work_z = float(default_work_z_raw) if default_work_z_raw else 0.0
    except ValueError:
        logger.warning(
            "NENABOT_DEFAULT_WORK_Z='%s' is not a valid float — using 0.0",
            default_work_z_raw,
        )
        default_work_z = 0.0

    default_measuring_points_per_cm_raw = _first_env(
        "NENABOT_DEFAULT_MEASURING_POINTS_PER_CM"
    )
    try:
        default_measuring_points_per_cm = (
            float(default_measuring_points_per_cm_raw)
            if default_measuring_points_per_cm_raw
            else 0.5
        )
        if default_measuring_points_per_cm <= 0:
            raise ValueError("must be > 0")
    except ValueError:
        logger.warning(
            "NENABOT_DEFAULT_MEASURING_POINTS_PER_CM='%s' is not a valid positive float — using 0.5",
            default_measuring_points_per_cm_raw,
        )
        default_measuring_points_per_cm = 0.5

    db = Database(db_path=db_path)
    db.init_db()

    robot = RobotAdapter()
    result = robot.connect_first_available()
    if result.ok:
        logger.info("Robot connected on startup")
        home_result = robot.home()
        if home_result.ok:
            logger.info("Robot homed on startup")
        else:
            logger.warning("Robot homing failed on startup: %s", home_result.error)
    else:
        logger.warning("Robot not connected on startup: %s", result.error)

    return OrchestratorService(
        camera_vision=CameraVisionAdapter(),
        robot=robot,
        ionvision=IVAdapter(
            base_url=ionvision_base_url,
            ws_base_url=ionvision_ws_base_url,
        ),
        storage=StorageAdapter(db=db),
        max_jobs=max_jobs,
        default_work_z=default_work_z,
        default_measuring_points_per_cm=default_measuring_points_per_cm,
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
