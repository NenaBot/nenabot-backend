"""Tests for the data-retention / cleanup functionality.

Covers:
- StorageAdapter.prune_jobs() — DB-level pruning
- OrchestratorService._prune_old_data() — combined DB + disk pruning
- NENABOT_MAX_JOBS env-var wiring in create_orchestrator()
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.adapters.camera_vision import CameraVisionAdapter, CaptureResult
from app.adapters.database import Database
from app.adapters.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter, RobotResult
from app.adapters.storage import StorageAdapter
from app.dependencies import create_orchestrator
from app.domain.models import Job, Waypoint
from app.services.orchestrator import OrchestratorService


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_storage(tmp_path: Path) -> StorageAdapter:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return StorageAdapter(db=db)


def _make_svc(tmp_path: Path, max_jobs: int = 0) -> OrchestratorService:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()

    camera = CameraVisionAdapter(output_dir=str(tmp_path / "images"))
    camera.ping = MagicMock(return_value=CaptureResult(ok=False, error="no camera"))

    robot = RobotAdapter()
    robot.ping = MagicMock(return_value=RobotResult(ok=False, error="no robot"))

    return OrchestratorService(
        camera_vision=camera,
        robot=robot,
        storage=StorageAdapter(db=db),
        dms=IVAdapter(
            base_url="http://localhost:8080", ws_base_url="ws://localhost:8080"
        ),
        max_jobs=max_jobs,
    )


def _insert_job(store: StorageAdapter, job_id: str, created_at: str) -> None:
    """Insert a minimal completed job with a given created_at timestamp."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    job = Job(
        id=job_id,
        path=[],
        dry_run=True,
        state="completed",
        created_at=created_at,
        updated_at=now,
    )
    store.save_job(job)


def _ts(offset_seconds: int = 0) -> str:
    """Return an ISO-8601 UTC timestamp, optionally offset by *offset_seconds*."""
    base = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    return (base + datetime.timedelta(seconds=offset_seconds)).isoformat()


# ── StorageAdapter.prune_jobs ─────────────────────────────────────────────────


def test_prune_jobs_removes_oldest(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    for i in range(5):
        _insert_job(store, f"job-{i}", _ts(i))

    deleted = store.prune_jobs(max_jobs=3)

    assert set(deleted) == {"job-0", "job-1"}
    remaining = [j.id for j in store.list_jobs()]
    assert set(remaining) == {"job-2", "job-3", "job-4"}


def test_prune_jobs_keeps_all_when_under_limit(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    for i in range(3):
        _insert_job(store, f"job-{i}", _ts(i))

    deleted = store.prune_jobs(max_jobs=5)

    assert deleted == []
    assert len(store.list_jobs()) == 3


def test_prune_jobs_keeps_all_when_exactly_at_limit(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    for i in range(4):
        _insert_job(store, f"job-{i}", _ts(i))

    deleted = store.prune_jobs(max_jobs=4)

    assert deleted == []
    assert len(store.list_jobs()) == 4


def test_prune_jobs_zero_is_noop(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    for i in range(3):
        _insert_job(store, f"job-{i}", _ts(i))

    deleted = store.prune_jobs(max_jobs=0)

    assert deleted == []
    assert len(store.list_jobs()) == 3


def test_prune_jobs_negative_is_noop(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    _insert_job(store, "job-1", _ts())

    deleted = store.prune_jobs(max_jobs=-1)

    assert deleted == []


def test_prune_jobs_cascades_child_rows(tmp_path: Path) -> None:
    """Deleting a job via prune must also remove its measurements and images."""
    from app.domain.models import Measurement

    store = _make_storage(tmp_path)
    _insert_job(store, "old", _ts(0))
    _insert_job(store, "new", _ts(1))

    store.save_measurement(
        "old",
        Measurement(
            waypoint_index=0,
            waypoint=Waypoint(x=1, y=2),
            simulated=True,
            timestamp=_ts(),
        ),
    )
    store.save_job_image("old", b"fake-image-bytes")

    store.prune_jobs(max_jobs=1)

    assert store.get_job("old") is None
    assert store.get_measurements("old") == []
    assert store.get_job_image("old") is None
    # Newer job survives
    assert store.get_job("new") is not None


def test_prune_jobs_empty_db_is_noop(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    deleted = store.prune_jobs(max_jobs=5)
    assert deleted == []


# ── OrchestratorService._prune_image_files ───────────────────────────────────


def _make_image_files(image_dir: Path, count: int) -> list[Path]:
    """Create *count* fake capture files with sequential mtime values."""
    image_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(count):
        f = image_dir / f"capture_2024-01-01T00-00-0{i}.jpg"
        f.write_bytes(b"fake")
        os.utime(f, (i, i))  # mtime = i seconds since epoch
        files.append(f)
    return files


def test_prune_image_files_removes_oldest(tmp_path: Path) -> None:
    files = _make_image_files(tmp_path / "images", 5)
    svc = _make_svc(tmp_path, max_jobs=3)
    svc._prune_image_files()

    remaining = {f.name for f in (tmp_path / "images").glob("capture_*.jpg")}
    assert len(remaining) == 3
    # Two oldest (mtime 0 and 1) must be gone; three newest survive
    assert files[0].name not in remaining
    assert files[1].name not in remaining
    assert files[2].name in remaining
    assert files[3].name in remaining
    assert files[4].name in remaining


def test_prune_image_files_ignores_non_capture_files(tmp_path: Path) -> None:
    """Files not matching capture_*.jpg must never be deleted."""
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    keep = image_dir / "other_file.jpg"
    keep.write_bytes(b"keep me")

    svc = _make_svc(tmp_path, max_jobs=1)
    svc._prune_image_files()

    assert keep.exists()


def test_prune_image_files_noop_when_max_jobs_zero(tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    _make_image_files(image_dir, 10)
    svc = _make_svc(tmp_path, max_jobs=0)
    svc._prune_image_files()

    assert len(list(image_dir.glob("capture_*.jpg"))) == 10


def test_prune_image_files_missing_dir_does_not_raise(tmp_path: Path) -> None:
    """If the images directory doesn't exist yet, pruning should not error."""
    svc = _make_svc(tmp_path, max_jobs=2)
    svc._prune_image_files()  # must not raise


def test_prune_image_files_triggered_by_detect_path(tmp_path: Path) -> None:
    """detect_path() must prune old capture files even when no job has run."""
    # Pre-populate excess files in the image directory
    image_dir = tmp_path / "images"
    _make_image_files(image_dir, 5)

    svc = _make_svc(tmp_path, max_jobs=3)

    # Mock capture() to write a new file without needing a real camera
    new_file = image_dir / "capture_2024-12-01T00-00-00.jpg"
    new_file.write_bytes(b"new capture")
    os.utime(new_file, (999, 999))  # newest mtime

    capture_mock = MagicMock(
        return_value=CaptureResult(ok=True, image_path=str(new_file))
    )
    svc._camera_vision.capture = capture_mock
    svc._camera_vision.detect = MagicMock(
        return_value=MagicMock(
            ok=False,
            error="no markers",
            pixels_per_mm=None,
            marker_corners=[],
            marker_count=0,
        )
    )
    svc._robot.get_pose = MagicMock(
        return_value=MagicMock(ok=False, error="no robot", x=0, y=0, z=0, r=0)
    )

    svc.detect_path()

    # 6 files existed before pruning (5 old + 1 new), max=3 → 3 must survive
    remaining = list(image_dir.glob("capture_*.jpg"))
    assert len(remaining) == 3
    # New file must be among the survivors (it has the highest mtime)
    assert new_file in remaining


# ── OrchestratorService._prune_old_data ──────────────────────────────────────


def test_prune_old_data_removes_db_jobs(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path, max_jobs=2)

    for i in range(4):
        _insert_job(svc._storage, f"job-{i}", _ts(i))

    svc._prune_old_data()

    remaining = [j.id for j in svc.list_jobs()]
    assert len(remaining) == 2
    assert set(remaining) == {"job-2", "job-3"}


def test_prune_old_data_also_removes_disk_images(tmp_path: Path) -> None:
    """_prune_old_data() must clean up disk files as well as DB rows."""
    _make_image_files(tmp_path / "images", 5)
    svc = _make_svc(tmp_path, max_jobs=3)
    svc._prune_old_data()

    remaining = list((tmp_path / "images").glob("capture_*.jpg"))
    assert len(remaining) == 3


def test_prune_old_data_noop_when_max_jobs_zero(tmp_path: Path) -> None:
    svc = _make_svc(tmp_path, max_jobs=0)

    for i in range(10):
        _insert_job(svc._storage, f"job-{i}", _ts(i))

    svc._prune_old_data()

    assert len(svc.list_jobs()) == 10


def test_prune_old_data_missing_image_dir_does_not_raise(tmp_path: Path) -> None:
    """If the images directory doesn't exist yet, pruning should not error."""
    svc = _make_svc(tmp_path, max_jobs=2)
    svc._prune_old_data()  # must not raise


# ── End-to-end: cleanup triggered by job completion ──────────────────────────


def test_cleanup_triggered_after_dry_run(tmp_path: Path) -> None:
    """After a dry-run job finishes, excess jobs should be pruned automatically."""
    svc = _make_svc(tmp_path, max_jobs=2)

    # Pre-populate 3 jobs that are already completed (older than the new one)
    for i in range(3):
        _insert_job(svc._storage, f"old-{i}", _ts(i))

    waypoints = [Waypoint(x=10, y=20)]
    job = svc.create_job(path=waypoints, dry_run=True)
    svc.run_job(job.id)

    # Join the background thread so the entire finally block — including
    # _prune_old_data() — has completed before we assert anything.
    assert svc._job_thread is not None
    svc._job_thread.join(timeout=10)

    # Total was 4 (3 old + 1 new). max_jobs=2 → 2 oldest pruned, 2 survive.
    all_jobs = svc.list_jobs()
    assert len(all_jobs) == 2
    # The newly completed job must be among survivors
    assert any(j.id == job.id for j in all_jobs)


# ── NENABOT_MAX_JOBS env-var wiring ──────────────────────────────────────────


def test_create_orchestrator_reads_max_jobs_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"NENABOT_MAX_JOBS": "7"}):
        with (
            patch("app.dependencies.RobotAdapter") as mock_robot_cls,
            patch("app.dependencies.CameraVisionAdapter"),
            patch("app.dependencies.IVAdapter"),
        ):
            mock_robot = MagicMock()
            mock_robot.connect_first_available.return_value = MagicMock(
                ok=False, error="no robot"
            )
            mock_robot_cls.return_value = mock_robot

            svc = create_orchestrator(db_path=str(tmp_path / "test.db"))

    assert svc._max_jobs == 7


def test_create_orchestrator_defaults_to_unlimited(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "NENABOT_MAX_JOBS"}
    with patch.dict(os.environ, env, clear=True):
        with (
            patch("app.dependencies.RobotAdapter") as mock_robot_cls,
            patch("app.dependencies.CameraVisionAdapter"),
            patch("app.dependencies.IVAdapter"),
        ):
            mock_robot = MagicMock()
            mock_robot.connect_first_available.return_value = MagicMock(
                ok=False, error="no robot"
            )
            mock_robot_cls.return_value = mock_robot

            svc = create_orchestrator(db_path=str(tmp_path / "test.db"))

    assert svc._max_jobs == 0


def test_create_orchestrator_invalid_max_jobs_defaults_to_zero(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"NENABOT_MAX_JOBS": "not-a-number"}):
        with (
            patch("app.dependencies.RobotAdapter") as mock_robot_cls,
            patch("app.dependencies.CameraVisionAdapter"),
            patch("app.dependencies.IVAdapter"),
        ):
            mock_robot = MagicMock()
            mock_robot.connect_first_available.return_value = MagicMock(
                ok=False, error="no robot"
            )
            mock_robot_cls.return_value = mock_robot

            svc = create_orchestrator(db_path=str(tmp_path / "test.db"))

    assert svc._max_jobs == 0
