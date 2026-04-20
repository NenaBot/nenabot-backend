from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit, urlunsplit

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter
from app.adapters.mock_camera_vision import MockCameraVisionAdapter
from app.adapters.mock_ionVision import MockIVAdapter
from app.adapters.mock_robot import MockRobotAdapter
from app.adapters.memory_storage import InMemoryStorageAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService

logger = logging.getLogger(__name__)
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


def _first_env(*names: str) -> str | None:
    """Return the first non-empty environment variable from the given names."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _env_flag(*names: str, default: bool = False) -> bool:
    """Parse the first configured env var as a boolean flag."""
    value = _first_env(*names)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_ENV_VALUES


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
    intrinsics_path: str | None = None,
    mapping_path: str | None = None,
    *,
    dms_base_url: str | None = None,
    dms_ws_base_url: str | None = None,
) -> OrchestratorService:
    """Create an OrchestratorService with default dependencies."""
    mock_mode_enabled = _env_flag("NENABOT_MOCK_MODE", default=False)
    ionvision_base_url = (
        ionvision_base_url
        or dms_base_url
        or _first_env("IONVISION_BASE_URL", "NENABOT_DMS_BASE_URL")
        or "http://localhost:8080"
    ).rstrip("/")
    ionvision_ws_base_url = (
        ionvision_ws_base_url
        or dms_ws_base_url
        or _first_env("IONVISION_WS_BASE_URL", "NENABOT_DMS_WS_BASE_URL")
        or _derive_ws_base_url(ionvision_base_url)
    ).rstrip("/")
    if mock_mode_enabled:
        intrinsics_path = "data/calibration/camera_params.json"
        mapping_path = "data/calibration/robot_mapping.json.example"
    else:
        intrinsics_path = (
            intrinsics_path
            or _first_env("NENABOT_INTRINSICS_PATH")
            or "data/calibration/camera_params.json"
        )
        mapping_path = (
            mapping_path
            or _first_env("NENABOT_MAPPING_PATH")
            or "data/calibration/robot_mapping.json"
        )
    mock_image_path = (
        _first_env("NENABOT_MOCK_IMAGE_PATH") or "data/calibration/mock.jpeg"
    )
    startup_homing_enabled = _env_flag(
        "NENABOT_ENABLE_STARTUP_HOMING",
        default=False,
    )

    max_jobs_raw = _first_env("NENABOT_MAX_JOBS")
    try:
        max_jobs = int(max_jobs_raw) if max_jobs_raw else 0
        if max_jobs < 0:
            raise ValueError("must be non-negative")
    except ValueError:
        logger.warning(
            "NENABOT_MAX_JOBS='%s' is not a valid non-negative integer — retention disabled",
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

    if mock_mode_enabled:
        logger.warning(
            "NENABOT_MOCK_MODE is enabled: running with mock robot/camera/ionvision adapters"
        )
        camera = MockCameraVisionAdapter(
            intrinsics_path=intrinsics_path,
            mock_image_path=mock_image_path,
        )
        robot = MockRobotAdapter()
        ionvision = MockIVAdapter(
            base_url=ionvision_base_url,
            ws_base_url=ionvision_ws_base_url,
        )
        storage = InMemoryStorageAdapter()
    else:
        db = Database(db_path=db_path)
        db.init_db()
        camera = CameraVisionAdapter(intrinsics_path=intrinsics_path)
        robot = RobotAdapter()
        ionvision = IVAdapter(
            base_url=ionvision_base_url,
            ws_base_url=ionvision_ws_base_url,
        )
        storage = StorageAdapter(db=db)
    default_measurement_threshold_raw = _first_env(
        "NENABOT_DEFAULT_MEASUREMENT_THRESHOLD"
    )
    try:
        default_measurement_threshold = (
            float(default_measurement_threshold_raw)
            if default_measurement_threshold_raw
            else 120.0
        )
        if not (0.0 <= default_measurement_threshold <= 255.0):
            raise ValueError("must be between 0 and 255")
    except ValueError:
        logger.warning(
            "NENABOT_DEFAULT_MEASUREMENT_THRESHOLD='%s' is not a valid float in [0,255] — using 120.0",
            default_measurement_threshold_raw,
        )
        default_measurement_threshold = 120.0

    result = robot.connect_first_available()
    if result.ok:
        logger.info("Robot connected on startup")
        if startup_homing_enabled:
            home_result = robot.home()
            if home_result.ok:
                logger.info("Robot homed on startup")
            else:
                logger.warning("Robot homing failed on startup: %s", home_result.error)
        else:
            logger.info(
                "Skipping robot homing on startup; set NENABOT_ENABLE_STARTUP_HOMING=1 to enable"
            )
    else:
        logger.warning("Robot not connected on startup: %s", result.error)

    return OrchestratorService(
        camera_vision=camera,
        robot=robot,
        ionvision=ionvision,
        storage=storage,
        mapping_path=mapping_path,
        max_jobs=max_jobs,
        default_work_z=default_work_z,
        default_measuring_points_per_cm=default_measuring_points_per_cm,
        default_measurement_threshold=default_measurement_threshold,
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
