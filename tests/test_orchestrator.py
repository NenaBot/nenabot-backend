import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.adapters.camera_vision import (
    CameraVisionAdapter,
    CaptureResult,
    CheckerboardResult,
    Corner,
)
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter, IVResult
from app.adapters.robot import PoseResult, RobotAdapter, RobotResult
from app.adapters.storage import StorageAdapter
from app.domain.models import Waypoint
from app.services.orchestrator import OrchestratorService
from tests.calibration_helpers import (
    sample_correspondences,
    write_intrinsics,
    write_mapping,
)


def _make_svc(
    tmp_path: Path, with_mapping: bool = False
) -> tuple[OrchestratorService, Path, Path]:
    intrinsics_path = write_intrinsics(tmp_path / "camera_intrinsics.json")
    mapping_path = tmp_path / "robot_mapping.json"
    if with_mapping:
        write_mapping(mapping_path, intrinsics_path)

    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()

    camera = CameraVisionAdapter(intrinsics_path=str(intrinsics_path))
    camera.ping = MagicMock(
        return_value=CaptureResult(ok=False, error="no camera in test")
    )
    camera.checkerboard_status = MagicMock(
        return_value={"visible": False, "error": "no camera in test"}
    )

    robot = RobotAdapter()
    robot.ping = MagicMock(return_value=RobotResult(ok=False, error="no robot in test"))

    ionvision = IVAdapter(
        base_url="http://localhost:8080",
        ws_base_url="ws://localhost:8080",
    )
    ionvision.ping = MagicMock(
        return_value=IVResult(ok=False, error="no ionvision in test")
    )

    service = OrchestratorService(
        camera_vision=camera,
        robot=robot,
        storage=StorageAdapter(db=db),
        ionvision=ionvision,
        mapping_path=str(mapping_path),
    )
    return service, intrinsics_path, mapping_path


def test_intrinsics_file_loading(tmp_path: Path) -> None:
    intrinsics_path = write_intrinsics(tmp_path / "camera_intrinsics.json")
    adapter = CameraVisionAdapter(intrinsics_path=str(intrinsics_path))
    assert adapter.intrinsics_loaded is True
    assert adapter.intrinsics_error is None


def test_intrinsics_invalid_file_handling(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad_intrinsics.json"
    bad_path.write_text("{not-json")
    adapter = CameraVisionAdapter(intrinsics_path=str(bad_path))
    assert adapter.intrinsics_loaded is False
    assert "Invalid intrinsic calibration file" in (adapter.intrinsics_error or "")


def test_create_job_creates_job(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    waypoints = [Waypoint(x=1, y=2), Waypoint(x=3, y=4, z=5, r=90)]
    job = service.create_job(path=waypoints, dry_run=True, options={"foo": "bar"})
    assert job.id
    assert job.options == {"foo": "bar"}
    assert len(job.path) == 2
    assert job.state == "created"

    fetched = service.get_job(job.id)
    assert fetched is not None
    assert fetched.options == {"foo": "bar"}
    assert len(fetched.path) == 2


def test_dry_run_completes(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    job = service.create_job(
        path=[Waypoint(x=10, y=20), Waypoint(x=30, y=40)], dry_run=True
    )
    service.run_job(job.id)

    db_job = None
    for _ in range(30):
        db_job = service.get_job(job.id)
        if db_job and db_job.state in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert db_job is not None
    assert db_job.state == "completed"
    assert db_job.last_point_processed == 2
    assert len(db_job.measurements) == 2


def test_stop_running_job(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    waypoints = [Waypoint(x=float(i), y=float(i)) for i in range(100)]
    job = service.create_job(path=waypoints, dry_run=True)
    service.run_job(job.id)
    time.sleep(0.35)

    assert service.stop_job() is True

    db_job = None
    for _ in range(20):
        db_job = service.get_job(job.id)
        if db_job and db_job.state in ("stopped", "completed"):
            break
        time.sleep(0.1)

    assert db_job is not None
    assert db_job.state == "stopped"
    assert db_job.last_point_processed < 100


def test_stop_when_no_job_running(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    assert service.stop_job() is False


def test_prevent_concurrent_job_execution(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    first_job = service.create_job(
        path=[Waypoint(x=float(i), y=float(i)) for i in range(100)],
        dry_run=True,
    )
    service.run_job(first_job.id)
    time.sleep(0.1)

    second_job = service.create_job(path=[Waypoint(x=1, y=2)], dry_run=True)
    with pytest.raises(RuntimeError, match="Another job is already running"):
        service.run_job(second_job.id)

    service.stop_job()


def test_health_returns_component_statuses(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    result = service.health()

    assert result["status"] in {"ok", "degraded"}
    assert result["uptime_s"] >= 0
    for key in ("robot", "camera", "ionvision"):
        assert key in result
        assert result[key]["status"] in {"connected", "disconnected", "error"}


def test_health_uptime_advances(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    first = service.health()
    time.sleep(0.15)
    second = service.health()
    assert second["uptime_s"] > first["uptime_s"]


def test_status_includes_calibration_block(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    status = service.status()
    assert status["state"] == "ready"
    calibration = status["calibration"]
    assert calibration["intrinsics_loaded"] is True
    assert calibration["checkerboard_visible"] is False
    assert calibration["calibrated"] is False
    assert calibration["last_calibrated_at"] is None


def test_status_reflects_running_job(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    assert service.status()["state"] == "ready"

    job = service.create_job(
        path=[Waypoint(x=float(i), y=float(i)) for i in range(50)],
        dry_run=True,
    )
    service.run_job(job.id)
    time.sleep(0.1)
    assert service.status()["state"] == "busy"

    service.stop_job()
    for _ in range(20):
        if service.status()["state"] == "ready":
            break
        time.sleep(0.1)
    assert service.status()["state"] == "ready"


def test_calibration_flow_writes_mapping_file_and_status_date(tmp_path: Path) -> None:
    service, intrinsics_path, mapping_path = _make_svc(tmp_path)
    image_points, robot_points = sample_correspondences()
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    service.camera_vision.get_latest_frame = MagicMock(return_value=frame)
    service.camera_vision.find_checkerboard = MagicMock(
        return_value=CheckerboardResult(
            ok=True,
            corners=[Corner(x=x, y=y) for x, y in image_points],
            target_points=[Corner(x=x, y=y) for x, y in image_points],
            image_size=(1280, 720),
        )
    )
    service.camera_vision.frame_to_base64 = MagicMock(return_value="encoded-image")
    service.camera_vision.checkerboard_visible = MagicMock(return_value=True)

    start_pose = PoseResult(ok=True, x=10.0, y=20.0, z=30.0, r=40.0)
    captured_poses = [
        PoseResult(ok=True, x=x, y=y, z=z, r=0.0) for x, y, z in robot_points
    ]
    service._robot.get_pose = MagicMock(side_effect=[start_pose, *captured_poses])

    start_response = service.calibration_action("start")
    assert start_response["ok"] is True
    assert start_response["referenceImageBase64"] == "encoded-image"
    assert start_response["currentStep"] == 0
    assert start_response["targetPoint"]["pixelX"] == 100.0
    assert start_response["targetPoint"]["pixelY"] == 100.0
    assert start_response["targetPoint"]["gridRow"] == 1
    assert start_response["targetPoint"]["gridCol"] == 0
    assert start_response["targetPoint"]["step"] == 1
    assert start_response["targetPoint"]["label"] == "P1 (1,0)"

    for expected_step in range(1, 5):
        response = service.calibration_action("capture")
        assert response["currentStep"] == expected_step

    assert mapping_path.exists()
    saved = json.loads(mapping_path.read_text())
    assert saved["intrinsics_path"] == str(intrinsics_path)
    assert saved["calibrated_at"]
    assert saved["plane"]["origin"] == pytest.approx([200.0, 100.0, -50.0])
    assert saved["plane"]["x_axis"] == pytest.approx([1.0, 0.0, 0.0])
    assert saved["plane"]["y_axis"] == pytest.approx([0.0, 1.0, 0.0])
    assert saved["plane"]["normal"] == pytest.approx([0.0, 0.0, -1.0])
    assert service.is_calibrated is True
    assert service.last_calibrated_at == saved["calibrated_at"]


def test_pixel_to_robot_uses_saved_mapping(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path, with_mapping=True)
    result = service.pixel_to_robot(150.0, 150.0, 5.0, 90.0)
    assert result.x == pytest.approx(250.0, abs=1.5)
    assert result.y == pytest.approx(150.0, abs=1.5)
    assert result.z == 5.0
    assert result.r == 90.0


def test_pixel_to_robot_raises_when_uncalibrated(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    with pytest.raises(RuntimeError, match="Not calibrated"):
        service.pixel_to_robot(150.0, 150.0, 0.0, 0.0)


def test_populate_pixel_path_from_batteries_generates_points(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path, with_mapping=True)
    path = service.populate_pixel_path_from_batteries(
        batteries=[
            [
                (100.0, 100.0),
                (200.0, 100.0),
                (200.0, 200.0),
                (100.0, 200.0),
            ]
        ],
        measuring_points_per_cm=0.5,
    )
    assert path
    assert path[0]["index"] == "0-0-0"
    assert path[0]["batteryNr"] == 0
    assert path[0]["cornerIndex"] == 0
    assert path[0]["measurementIndex"] == 0
    assert len(path) == 20


def test_job_fails_on_robot_move_error(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    job = service.create_job(path=[Waypoint(x=1, y=2)], dry_run=False)
    with patch.object(
        service._robot,
        "move",
        return_value=RobotResult(ok=False, error="Connection lost"),
    ):
        service.run_job(job.id)
        assert service._job_thread is not None
        service._job_thread.join(timeout=10)

    db_job = service.get_job(job.id)
    assert db_job is not None
    assert db_job.state == "failed"
    assert "Robot move failed" in (db_job.error or "")


def test_return_to_start_after_completion(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    start = Waypoint(x=0, y=0, z=0, r=0)
    target = Waypoint(x=10, y=20, z=0, r=0)
    job = service.create_job(path=[target], dry_run=False, starting_point=start)

    move_calls: list[tuple[float, float, float, float]] = []

    def track_move(x, y, z, r):
        move_calls.append((x, y, z, r))
        return RobotResult(ok=True)

    with patch.object(service._robot, "move", side_effect=track_move), patch.object(
        service._robot,
        "wait_for_position",
        return_value=PoseResult(ok=True, x=0, y=0, z=0, r=0),
    ), patch.object(
        service._ionvision,
        "start_new_scan",
        return_value=IVResult(ok=True),
    ), patch.object(
        service._ionvision,
        "get_current_scan",
        return_value=IVResult(ok=True, payload={"state": "finished"}),
    ), patch.object(
        service._ionvision,
        "get_latest_dataobject",
        return_value=IVResult(ok=True, payload={"data": "test"}),
    ), patch("time.sleep"):
        service.run_job(job.id)
        assert service._job_thread is not None
        service._job_thread.join(timeout=10)

    db_job = service.get_job(job.id)
    assert db_job is not None
    assert db_job.state == "completed"
    assert move_calls[0] == (10, 20, 0, 0)
    assert move_calls[-1] == (0, 0, 0, 0)


def test_clean_image_saved_without_overlay(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)

    dummy_image = b"fake_jpeg_data"
    waypoints = [Waypoint(x=1, y=2), Waypoint(x=3, y=4)]
    job = service.create_job(path=waypoints, dry_run=True, image_bytes=dummy_image)

    stored = service.get_job_image(job.id)
    assert stored == dummy_image


def test_profiles_and_default(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    profiles = service.profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "default"

    default = service.default_profile()
    assert default["name"] == "default"
    assert "description" in default


def test_default_profile_work_z_defaults_to_zero(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    assert service.default_profile()["workZ"] == 0.0
    assert service.default_profile()["measuringPointsPerCm"] == pytest.approx(0.5)


def test_default_profile_work_z_uses_constructor_param(tmp_path: Path) -> None:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    camera = CameraVisionAdapter()
    camera.ping = MagicMock(
        return_value=CaptureResult(ok=False, error="no camera in test")
    )
    robot = RobotAdapter()
    robot.ping = MagicMock(return_value=RobotResult(ok=False, error="no robot in test"))
    svc = OrchestratorService(
        camera_vision=camera,
        robot=robot,
        storage=StorageAdapter(db=db),
        ionvision=IVAdapter(
            base_url="http://localhost:8080",
            ws_base_url="ws://localhost:8080",
        ),
        default_work_z=-35.0,
        default_measuring_points_per_cm=1.25,
    )
    assert svc.default_profile()["workZ"] == -35.0
    assert svc.default_profile()["measuringPointsPerCm"] == pytest.approx(1.25)


def test_create_orchestrator_reads_default_work_z_env(tmp_path: Path) -> None:
    from app.dependencies import create_orchestrator

    with patch(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        return_value=RobotResult(ok=False, error="no robot"),
    ), patch.dict(
        os.environ,
        {
            "NENABOT_DEFAULT_WORK_Z": "-42.5",
            "NENABOT_DEFAULT_MEASURING_POINTS_PER_CM": "0.8",
        },
    ):
        svc = create_orchestrator(
            db_path=str(tmp_path / "test.db"),
            ionvision_base_url="http://localhost:8080",
        )
    assert svc.default_profile()["workZ"] == pytest.approx(-42.5)
    assert svc.default_profile()["measuringPointsPerCm"] == pytest.approx(0.8)


def test_create_orchestrator_invalid_work_z_falls_back(tmp_path: Path) -> None:
    from app.dependencies import create_orchestrator

    with patch(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        return_value=RobotResult(ok=False, error="no robot"),
    ), patch.dict(
        os.environ,
        {
            "NENABOT_DEFAULT_WORK_Z": "not-a-number",
            "NENABOT_DEFAULT_MEASURING_POINTS_PER_CM": "0",
        },
    ):
        svc = create_orchestrator(
            db_path=str(tmp_path / "test.db"),
            ionvision_base_url="http://localhost:8080",
        )
    assert svc.default_profile()["workZ"] == 0.0
    assert svc.default_profile()["measuringPointsPerCm"] == pytest.approx(0.5)


def test_move_robot_delegates_to_adapter(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    with patch.object(
        service._robot,
        "move",
        return_value=RobotResult(ok=True),
    ) as mock_move:
        result = service.move_robot(1.0, 2.0, 3.0, 4.0)
        assert result.ok is True
    mock_move.assert_called_once_with(1.0, 2.0, 3.0, 4.0)


def test_get_robot_pose_delegates_to_adapter(tmp_path: Path) -> None:
    service, _, _ = _make_svc(tmp_path)
    expected = PoseResult(
        ok=True,
        x=1.0,
        y=2.0,
        z=3.0,
        r=4.0,
        j1=5.0,
        j2=6.0,
        j3=7.0,
        j4=8.0,
    )
    with patch.object(service._robot, "get_pose", return_value=expected) as mock_pose:
        result = service.get_robot_pose()
        assert result.ok is True
        assert result.x == 1.0
        assert result.y == 2.0
        assert result.z == 3.0
        assert result.r == 4.0
        assert result.j1 == 5.0
    mock_pose.assert_called_once()
