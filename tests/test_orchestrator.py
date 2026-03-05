import time
from pathlib import Path

from app.adapters.camera_vision import CameraVisionAdapter
<<<<<<< HEAD
from app.adapters.database import Database
from app.adapters.ionVision.ionVision import IVAdapter
=======
from app.adapters.ionVision import IVAdapter
>>>>>>> d2ca401 (Feature/websocket api (#13))
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.domain.models import Waypoint
from app.services.orchestrator import OrchestratorService


def _make_svc(tmp_path: Path) -> OrchestratorService:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return OrchestratorService(
        camera_vision=CameraVisionAdapter(),
        robot=RobotAdapter(),
<<<<<<< HEAD
        dms=IVAdapter(base_url="http://localhost:8080"),
        storage=StorageAdapter(db=db),
=======
        dms=IVAdapter(base_url="http://localhost:8080",ws_base_url="ws://localhost:8080"),
        storage=StorageAdapter(base_dir=str(tmp_path)),
>>>>>>> d2ca401 (Feature/websocket api (#13))
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
