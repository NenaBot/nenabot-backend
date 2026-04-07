from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.adapters.camera_vision import CameraVisionAdapter
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter
from app.adapters.mock_camera_vision import MockCameraVisionAdapter
from app.adapters.mock_ionVision import MockIVAdapter
from app.adapters.mock_robot import MockRobotAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.services.orchestrator import OrchestratorService

logger = logging.getLogger(__name__)
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_MOCK_IMAGE_POINTS = [
    (100.0, 100.0),
    (200.0, 100.0),
    (200.0, 200.0),
    (100.0, 200.0),
]
_MOCK_ROBOT_POINTS = [
    (200.0, 100.0, -50.0),
    (300.0, 100.0, -50.0),
    (300.0, 200.0, -50.0),
    (200.0, 200.0, -50.0),
]


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


def _ensure_mock_calibration_files(intrinsics_path: str, mapping_path: str) -> None:
    """Create deterministic mock calibration artifacts if they do not exist."""
    intrinsics_file = Path(intrinsics_path)
    mapping_file = Path(mapping_path)

    if not intrinsics_file.exists():
        intrinsics_file.parent.mkdir(parents=True, exist_ok=True)
        intrinsics = {
            "camera_matrix": [
                [1000.0, 0.0, 640.0],
                [0.0, 1000.0, 360.0],
                [0.0, 0.0, 1.0],
            ],
            "dist_coeff": [[0.0, 0.0, 0.0, 0.0, 0.0]],
            "resolution": [1280, 720],
            "checkerboard": {
                "inner_corners": [8, 6],
                "square_size_mm": 34.0,
            },
        }
        intrinsics_file.write_text(json.dumps(intrinsics, indent=4))

    if mapping_file.exists():
        return

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        logger.warning(
            "Mock mode: unable to generate mapping file (missing cv2/numpy): %s",
            exc,
        )
        return

    camera_matrix = np.array(
        [
            [1000.0, 0.0, 640.0],
            [0.0, 1000.0, 360.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist_coeff = np.array([[0.0, 0.0, 0.0, 0.0, 0.0]], dtype=np.float64)

    success, rvec, tvec = cv2.solvePnP(
        np.array(_MOCK_ROBOT_POINTS, dtype=np.float64),
        np.array(_MOCK_IMAGE_POINTS, dtype=np.float64).reshape(-1, 1, 2),
        camera_matrix,
        dist_coeff,
    )
    if not success:
        logger.warning("Mock mode: solvePnP failed; mapping file not generated")
        return

    mapping = {
        "calibrated_at": "2026-04-07T00:00:00+00:00",
        "intrinsics_path": str(intrinsics_file),
        "resolution": [1280, 720],
        "checkerboard": {
            "inner_corners": [8, 6],
            "square_size_mm": 34.0,
            "fixed_points": [[1, 0], [1, 6], [5, 7], [5, 0]],
        },
        "image_points": [
            {
                "row": row,
                "col": col,
                "pixelX": point[0],
                "pixelY": point[1],
            }
            for (row, col), point in zip(
                ((1, 0), (1, 6), (5, 7), (5, 0)),
                _MOCK_IMAGE_POINTS,
            )
        ],
        "robot_points": [
            {
                "row": row,
                "col": col,
                "robotX": point[0],
                "robotY": point[1],
                "robotZ": point[2],
            }
            for (row, col), point in zip(
                ((1, 0), (1, 6), (5, 7), (5, 0)),
                _MOCK_ROBOT_POINTS,
            )
        ],
        "start_pose": {"x": 200.0, "y": 100.0, "z": -50.0, "r": 0.0},
        "rvec": rvec.tolist(),
        "tvec": tvec.tolist(),
        "plane": {
            "origin": [200.0, 100.0, -50.0],
            "x_axis": [1.0, 0.0, 0.0],
            "y_axis": [0.0, 1.0, 0.0],
            "normal": [0.0, 0.0, -1.0],
        },
    }

    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    mapping_file.write_text(json.dumps(mapping, indent=4))


def create_orchestrator(
    db_path: str = "data/nenabot.db",
    dms_base_url: str | None = None,
    dms_ws_base_url: str | None = None,
    intrinsics_path: str | None = None,
    mapping_path: str | None = None,
) -> OrchestratorService:
    """Create an OrchestratorService with default dependencies."""
    mock_mode_enabled = _env_flag("NENABOT_MOCK_MODE", default=False)

    dms_base_url = (
        dms_base_url
        or _first_env("IONVISION_BASE_URL", "NENABOT_DMS_BASE_URL")
        or "http://localhost:8080"
    ).rstrip("/")
    dms_ws_base_url = (
        dms_ws_base_url
        or _first_env("IONVISION_WS_BASE_URL", "NENABOT_DMS_WS_BASE_URL")
        or _derive_ws_base_url(dms_base_url)
    ).rstrip("/")
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

    db = Database(db_path=db_path)
    db.init_db()

    if mock_mode_enabled:
        _ensure_mock_calibration_files(intrinsics_path, mapping_path)
        logger.warning(
            "NENABOT_MOCK_MODE is enabled: running with mock robot/camera/ionvision adapters"
        )
        camera = MockCameraVisionAdapter(intrinsics_path=intrinsics_path)
        robot = MockRobotAdapter()
        dms = MockIVAdapter(base_url=dms_base_url, ws_base_url=dms_ws_base_url)
    else:
        camera = CameraVisionAdapter(intrinsics_path=intrinsics_path)
        robot = RobotAdapter()
        dms = IVAdapter(base_url=dms_base_url, ws_base_url=dms_ws_base_url)

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
        dms=dms,
        storage=StorageAdapter(db=db),
        mapping_path=mapping_path,
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
