import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.adapters.camera_vision import (
    CameraVisionAdapter,
    CaptureResult,
    Corner,
    DetectionResult,
    DetectionResults,
    MarkerCorners,
)
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter, IVResult
from app.adapters.robot import PoseResult, RobotAdapter, RobotResult
from app.adapters.storage import StorageAdapter
from app.domain.models import Waypoint
from app.services.orchestrator import OrchestratorService


def _make_svc(tmp_path: Path) -> OrchestratorService:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()

    camera = CameraVisionAdapter()
    camera.ping = MagicMock(
        return_value=CaptureResult(ok=False, error="no camera in test")
    )

    robot = RobotAdapter()
    robot.ping = MagicMock(return_value=RobotResult(ok=False, error="no robot in test"))

    return OrchestratorService(
        camera_vision=camera,
        robot=robot,
        storage=StorageAdapter(db=db),
        dms=IVAdapter(
            base_url="http://localhost:8080", ws_base_url="ws://localhost:8080"
        ),
    )


def test_create_job_creates_job(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path)
    waypoints = [Waypoint(x=1, y=2), Waypoint(x=3, y=4, z=5, r=90)]
    job = svc.create_job(path=waypoints, dry_run=True, options={"foo": "bar"})
    assert job.id
    assert job.options == {"foo": "bar"}
    assert len(job.path) == 2
    assert job.path[0].x == 1
    assert job.dry_run is True
    assert job.state == "created"

    # Verify it round-trips through the DB
    fetched = svc.get_job(job.id)
    assert fetched is not None
    assert fetched.options == {"foo": "bar"}
    assert len(fetched.path) == 2
    assert fetched.dry_run is True


def test_dry_run_completes(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path)
    waypoints = [Waypoint(x=10, y=20), Waypoint(x=30, y=40)]
    job = svc.create_job(path=waypoints, dry_run=True)
    svc.run_job(job.id)

    # Poll the DB for completion (in-memory ref isn't updated)
    db_job = None
    for _ in range(30):
        db_job = svc.get_job(job.id)
        if db_job and db_job.state in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert db_job is not None
    assert db_job.state == "completed"
    assert db_job.last_point_processed == 2
    assert len(db_job.measurements) == 2
    for m in db_job.measurements:
        assert m.simulated is True
        assert m.timestamp


def test_stop_running_job(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path)
    waypoints = [Waypoint(x=float(i), y=float(i)) for i in range(100)]
    job = svc.create_job(path=waypoints, dry_run=True)
    svc.run_job(job.id)
    time.sleep(0.3)

    assert svc.stop_job() is True

    db_job = None
    for _ in range(20):
        db_job = svc.get_job(job.id)
        if db_job and db_job.state in ("stopped", "completed"):
            break
        time.sleep(0.1)

    assert db_job is not None
    assert db_job.state == "stopped"
    assert db_job.last_point_processed < 100


def test_health_returns_component_statuses(tmp_path: Path) -> None:
    """health() should probe each adapter and report per-component status."""
    svc = _make_svc(tmp_path)
    result = svc.health()

    assert result["status"] in {"ok", "degraded"}
    assert result["uptime_s"] >= 0

    for key in ("robot", "camera", "dms"):
        assert key in result
        assert result[key]["status"] in {"connected", "disconnected", "error"}


def test_health_uptime_advances(tmp_path: Path) -> None:
    """uptime should increase between successive health() calls."""
    svc = _make_svc(tmp_path)
    h1 = svc.health()
    time.sleep(0.15)
    h2 = svc.health()
    assert h2["uptime_s"] > h1["uptime_s"]


def test_status_reflects_running_job(tmp_path: Path) -> None:
    """status() should return 'busy' while a job is executing."""
    svc = _make_svc(tmp_path)
    assert svc.status() == "ready"

    waypoints = [Waypoint(x=float(i), y=float(i)) for i in range(50)]
    job = svc.create_job(path=waypoints, dry_run=True)
    svc.run_job(job.id)
    time.sleep(0.1)
    assert svc.status() == "busy"

    svc.stop_job()
    for _ in range(20):
        if svc.status() == "ready":
            break
        time.sleep(0.1)
    assert svc.status() == "ready"


# ---- ORC-TC-004: Stop when no job is running ----


def test_stop_when_no_job_running(tmp_path: Path) -> None:
    """stop_job() should return False and have no side effects when idle."""
    svc = _make_svc(tmp_path)
    assert svc.stop_job() is False


# ---- ORC-TC-005: Prevent concurrent job execution ----


def test_prevent_concurrent_job_execution(tmp_path: Path) -> None:
    """run_job() should raise RuntimeError if another job is already running."""
    svc = _make_svc(tmp_path)
    waypoints_a = [Waypoint(x=float(i), y=float(i)) for i in range(100)]
    job_a = svc.create_job(path=waypoints_a, dry_run=True)
    svc.run_job(job_a.id)
    time.sleep(0.1)

    job_b = svc.create_job(path=[Waypoint(x=1, y=2)], dry_run=True)
    with pytest.raises(RuntimeError, match="Another job is already running"):
        svc.run_job(job_b.id)

    svc.stop_job()
    for _ in range(20):
        if svc.status() == "ready":
            break
        time.sleep(0.1)


# ---- ORC-TC-010: pixel_to_robot coordinate conversion ----


def test_pixel_to_robot_conversion(tmp_path: Path) -> None:
    """pixel_to_robot() should correctly apply the calibration formula."""
    svc = _make_svc(tmp_path)
    svc._cal_robot_start = Waypoint(x=100.0, y=200.0, z=0.0, r=0.0)
    svc._cal_canvas_start = (640.0, 400.0)
    svc._cal_pixels_per_mm = 2.0

    result = svc.pixel_to_robot(660.0, 380.0, 5.0, 90.0)
    # dpx = 660 - 640 = 20, dpy = 380 - 400 = -20
    # robot.x = 100 - (-20 / 2) = 110
    # robot.y = 200 - (20 / 2) = 190
    assert result.x == pytest.approx(110.0)
    assert result.y == pytest.approx(190.0)
    assert result.z == 5.0
    assert result.r == 90.0


# ---- ORC-TC-011: pixel_to_robot raises when uncalibrated ----


def test_pixel_to_robot_raises_when_uncalibrated(tmp_path: Path) -> None:
    """pixel_to_robot() should raise RuntimeError without calibration."""
    svc = _make_svc(tmp_path)
    with pytest.raises(RuntimeError, match="Not calibrated"):
        svc.pixel_to_robot(100, 200, 0, 0)


# ---- ORC-TC-012: is_calibrated property reflects state ----


def test_is_calibrated_property(tmp_path: Path) -> None:
    """is_calibrated should be False until all three calibration values are set."""
    svc = _make_svc(tmp_path)
    assert svc.is_calibrated is False

    svc._cal_robot_start = Waypoint(x=100, y=200)
    assert svc.is_calibrated is False

    svc._cal_canvas_start = (640.0, 400.0)
    assert svc.is_calibrated is False

    svc._cal_pixels_per_mm = 2.0
    assert svc.is_calibrated is True


# ---- ORC-TC-013: sort_pixel_path_from_canvas_start path ordering ----


def test_sort_pixel_path_from_canvas_start_orders_nearest_neighbor(
    tmp_path: Path,
) -> None:
    """sort_pixel_path_from_canvas_start should anchor at canvas start and return sorted waypoints only."""
    svc = _make_svc(tmp_path)
    svc._cal_canvas_start = (640.0, 400.0)

    waypoints = [
        (700.0, 400.0),
        (642.0, 401.0),
        (650.0, 400.0),
    ]

    sorted_points = svc.sort_pixel_path_from_canvas_start(waypoints)
    assert sorted_points == [
        (642.0, 401.0),
        (650.0, 400.0),
        (700.0, 400.0),
    ]
    assert (640.0, 400.0) not in sorted_points


def test_sort_pixel_path_from_canvas_start_raises_when_uncalibrated(
    tmp_path: Path,
) -> None:
    """sort_pixel_path_from_canvas_start should raise without canvas start calibration."""
    svc = _make_svc(tmp_path)
    with pytest.raises(RuntimeError, match="Not calibrated"):
        svc.sort_pixel_path_from_canvas_start([(1.0, 2.0)])


def test_detect_path_returns_sorted_detections(tmp_path: Path) -> None:
    """detect_path() should return detections sorted by nearest-neighbor from canvas start."""
    svc = _make_svc(tmp_path)

    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"fake-jpeg")
    marker = MarkerCorners(
        corners=[
            Corner(x=10.0, y=10.0),
            Corner(x=20.0, y=10.0),
            Corner(x=20.0, y=20.0),
            Corner(x=10.0, y=20.0),
        ]
    )

    # Create detections at various positions: unsorted
    detections = [
        DetectionResult(
            corners=[],
            width_mm=50.0,
            height_mm=50.0,
            center_x=700.0,  # far right
            center_y=400.0,
        ),
        DetectionResult(
            corners=[],
            width_mm=50.0,
            height_mm=50.0,
            center_x=642.0,  # closest to canvas start
            center_y=401.0,
        ),
        DetectionResult(
            corners=[],
            width_mm=50.0,
            height_mm=50.0,
            center_x=650.0,  # middle distance
            center_y=400.0,
        ),
    ]

    with patch.object(
        svc._camera_vision,
        "capture",
        return_value=CaptureResult(ok=True, image_path=str(image_path)),
    ), patch.object(
        svc._camera_vision,
        "detect",
        return_value=DetectionResults(
            ok=True,
            detections=detections,
            pixels_per_mm=2.0,
            marker_count=1,
            marker_corners=[marker],
            error=None,
        ),
    ), patch.object(
        svc._robot,
        "get_pose",
        return_value=PoseResult(ok=True, x=100.0, y=200.0, z=0.0, r=0.0),
    ):
        result = svc.detect_path()

    assert result.ok is True
    assert len(result.detections) == 3
    # Verify detections are sorted by nearest-neighbor from canvas start (640, 450)
    # Expected order: (642, 401) → (650, 400) → (700, 400)
    assert result.detections[0].center_x == 642.0
    assert result.detections[0].center_y == 401.0
    assert result.detections[1].center_x == 650.0
    assert result.detections[1].center_y == 400.0
    assert result.detections[2].center_x == 700.0
    assert result.detections[2].center_y == 400.0


# ---- ORC-TC-014: Job fails on robot move error ----


def test_job_fails_on_robot_move_error(tmp_path: Path) -> None:
    """A failing robot.move() should set job state to 'failed'."""
    svc = _make_svc(tmp_path)
    job = svc.create_job(path=[Waypoint(x=1, y=2)], dry_run=False)

    with patch.object(
        svc._robot,
        "move",
        return_value=RobotResult(ok=False, error="Connection lost"),
    ):
        svc.run_job(job.id)
        svc._job_thread.join(timeout=10)

    db_job = svc.get_job(job.id)
    assert db_job is not None
    assert db_job.state == "failed"
    assert "Robot move failed" in db_job.error


# ---- ORC-TC-015: Job fails on position arrival timeout ----


def test_job_fails_on_arrival_timeout(tmp_path: Path) -> None:
    """A wait_for_position timeout should set job state to 'failed'."""
    svc = _make_svc(tmp_path)
    job = svc.create_job(path=[Waypoint(x=1, y=2)], dry_run=False)

    with patch.object(
        svc._robot, "move", return_value=RobotResult(ok=True)
    ), patch.object(
        svc._robot,
        "wait_for_position",
        return_value=PoseResult(ok=False, error="Timeout waiting"),
    ):
        svc.run_job(job.id)
        svc._job_thread.join(timeout=10)

    db_job = svc.get_job(job.id)
    assert db_job is not None
    assert db_job.state == "failed"
    assert "Arm did not reach waypoint" in db_job.error


# ---- ORC-TC-016: Return to start after completion ----


def test_return_to_start_after_completion(tmp_path: Path) -> None:
    """After completing all waypoints, robot should move back to the starting position."""
    svc = _make_svc(tmp_path)
    start = Waypoint(x=0, y=0, z=0, r=0)
    target = Waypoint(x=10, y=20, z=0, r=0)
    job = svc.create_job(path=[target], dry_run=False, starting_point=start)

    move_calls: list[tuple[float, float, float, float]] = []

    def track_move(x, y, z, r):
        move_calls.append((x, y, z, r))
        return RobotResult(ok=True)

    with patch.object(svc._robot, "move", side_effect=track_move), patch.object(
        svc._robot,
        "wait_for_position",
        return_value=PoseResult(ok=True, x=0, y=0, z=0, r=0),
    ), patch.object(
        svc._dms, "start_new_scan", return_value=IVResult(ok=True)
    ), patch.object(
        svc._dms,
        "get_current_scan",
        return_value=IVResult(ok=True, payload={"state": "finished"}),
    ), patch.object(
        svc._dms,
        "get_latest_dataobject",
        return_value=IVResult(ok=True, payload={"data": "test"}),
    ), patch(
        "time.sleep"
    ):
        svc.run_job(job.id)
        svc._job_thread.join(timeout=10)

    db_job = svc.get_job(job.id)
    assert db_job is not None
    assert db_job.state == "completed"
    # Last move call should be back to the starting point (stored separately)
    assert move_calls[-1] == (0.0, 0.0, 0.0, 0.0)


# ---- ORC-TC-017: Clean base image saved (no overlay rendering) ----


def test_clean_image_saved_without_overlay(tmp_path: Path) -> None:
    """create_job should save the clean image directly, not a rendered overlay."""
    svc = _make_svc(tmp_path)

    dummy_image = b"fake_jpeg_data"
    waypoints = [Waypoint(x=1, y=2), Waypoint(x=3, y=4)]
    job = svc.create_job(path=waypoints, dry_run=True, image_bytes=dummy_image)

    stored = svc.get_job_image(job.id)
    assert stored == dummy_image  # saved as-is, no rendering


# ---- ORC-TC-018: Profile listing and default selection ----


def test_profiles_and_default(tmp_path: Path) -> None:
    """profiles() returns both profiles, default_profile() returns the first."""
    svc = _make_svc(tmp_path)
    profiles = svc.profiles()
    assert len(profiles) == 2
    assert profiles[0]["name"] == "default"
    assert profiles[1]["name"] == "fast"

    default = svc.default_profile()
    assert default["name"] == "default"
    assert "description" in default


# ---- ORC-TC-019: Manual move via orchestrator ----


def test_move_robot_delegates_to_adapter(tmp_path: Path) -> None:
    """move_robot() should delegate to robot.move() and return the result."""
    svc = _make_svc(tmp_path)
    with patch.object(
        svc._robot, "move", return_value=RobotResult(ok=True)
    ) as mock_move:
        result = svc.move_robot(1.0, 2.0, 3.0, 4.0)
        assert result.ok is True
    mock_move.assert_called_once_with(1.0, 2.0, 3.0, 4.0)


# ---- ORC-TC-020: Get robot pose via orchestrator ----


def test_get_robot_pose_delegates_to_adapter(tmp_path: Path) -> None:
    """get_robot_pose() should delegate to robot.get_pose() and return the result."""
    svc = _make_svc(tmp_path)
    expected = PoseResult(
        ok=True, x=1.0, y=2.0, z=3.0, r=4.0, j1=5.0, j2=6.0, j3=7.0, j4=8.0
    )
    with patch.object(svc._robot, "get_pose", return_value=expected) as mock_pose:
        result = svc.get_robot_pose()
        assert result.ok is True
        assert result.x == 1.0
        assert result.y == 2.0
        assert result.z == 3.0
        assert result.r == 4.0
        assert result.j1 == 5.0
    mock_pose.assert_called_once()
