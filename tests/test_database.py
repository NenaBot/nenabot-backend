"""Unit tests for Database and StorageAdapter."""

import datetime
from pathlib import Path

from app.adapters.database import Database
from app.adapters.storage import StorageAdapter
from app.domain.models import Job, Measurement, Waypoint


def _make_storage(tmp_path: Path) -> StorageAdapter:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    return StorageAdapter(db=db)


def _sample_job(**overrides) -> Job:
    defaults = dict(
        id="j-1",
        options={"speed": 10},
        path=[Waypoint(x=1, y=2), Waypoint(x=3, y=4, z=5, r=90)],
        dry_run=True,
        log=None,
        measurements=[],
        path_image=None,
        state="created",
        last_point_processed=0,
        error=None,
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    defaults.update(overrides)
    return Job(**defaults)


# ── Database-level tests ──────────────────────────────────────


def test_init_creates_tables(tmp_path: Path) -> None:
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    rows = db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r["name"] for r in rows}
    assert {"jobs", "waypoints", "measurements", "job_images"}.issubset(names)


# ── StorageAdapter: Job CRUD ──────────────────────────────────


def test_save_and_get_job(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    job = _sample_job()
    store.save_job(job)

    fetched = store.get_job("j-1")
    assert fetched is not None
    assert fetched.id == "j-1"
    assert fetched.options == {"speed": 10}
    assert len(fetched.path) == 2
    assert fetched.path[0].x == 1
    assert fetched.path[1].z == 5
    assert fetched.dry_run is True
    assert fetched.state == "created"


def test_list_jobs(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job(id="a"))
    store.save_job(_sample_job(id="b"))
    store.save_job(_sample_job(id="c"))
    jobs = store.list_jobs()
    assert len(jobs) == 3


def test_latest_job(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job(id="old"))
    store.save_job(_sample_job(id="new"))
    latest = store.latest_job()
    assert latest is not None
    assert latest.id == "new"


def test_update_job_state(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job())
    store.update_job_state("j-1", state="running", last_point_processed=3, error=None)
    job = store.get_job("j-1")
    assert job is not None
    assert job.state == "running"
    assert job.last_point_processed == 3


def test_delete_job(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job())
    store.delete_job("j-1")
    assert store.get_job("j-1") is None


# ── StorageAdapter: Measurements ──────────────────────────────


def test_save_and_get_measurements(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job())

    m = Measurement(
        waypoint_index=0,
        waypoint=Waypoint(x=1, y=2),
        scan_result={"voltage": 3.14},
        simulated=True,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    store.save_measurement("j-1", m)

    measurements = store.get_measurements("j-1")
    assert len(measurements) == 1
    assert measurements[0].waypoint_index == 0
    assert measurements[0].scan_result["voltage"] == 3.14
    assert measurements[0].simulated is True


# ── StorageAdapter: Images ────────────────────────────────────


def test_save_and_get_image(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job())

    blob = b"\xff\xd8\xff\xe0fake-jpeg-data"
    store.save_job_image("j-1", blob)

    fetched = store.get_job_image("j-1")
    assert fetched == blob


def test_get_image_returns_none_when_missing(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job())
    assert store.get_job_image("j-1") is None


# ── Cascade delete ────────────────────────────────────────────


def test_delete_cascades(tmp_path: Path) -> None:
    store = _make_storage(tmp_path)
    store.save_job(_sample_job())

    store.save_measurement(
        "j-1",
        Measurement(
            waypoint_index=0,
            waypoint=Waypoint(x=1, y=2),
            scan_result={},
            simulated=True,
            timestamp="2024-01-01T00:00:00Z",
        ),
    )
    store.save_job_image("j-1", b"img")

    store.delete_job("j-1")

    assert store.get_job("j-1") is None
    assert store.get_measurements("j-1") == []
    assert store.get_job_image("j-1") is None
