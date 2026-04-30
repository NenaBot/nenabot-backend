from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from app.adapters.memory_storage import InMemoryStorageAdapter
from app.adapters.mock_camera_vision import MockCameraVisionAdapter
from app.adapters.mock_ionVision import MockIVAdapter
from app.adapters.mock_robot import MockRobotAdapter
from app.adapters.robot import RobotResult
from app.dependencies import create_orchestrator
from app.domain.models import Waypoint


def test_create_orchestrator_does_not_home_robot_on_startup_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("NENABOT_ENABLE_STARTUP_HOMING", raising=False)

    connect_first_available = MagicMock(return_value=RobotResult(ok=True))
    home = MagicMock(return_value=RobotResult(ok=True))
    monkeypatch.setattr(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        connect_first_available,
    )
    monkeypatch.setattr("app.adapters.robot.RobotAdapter.home", home)

    create_orchestrator(db_path=str(tmp_path / "test.db"))

    connect_first_available.assert_called_once()
    home.assert_not_called()


def test_create_orchestrator_homes_robot_when_startup_homing_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NENABOT_ENABLE_STARTUP_HOMING", "1")

    connect_first_available = MagicMock(return_value=RobotResult(ok=True))
    home = MagicMock(return_value=RobotResult(ok=True))
    monkeypatch.setattr(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        connect_first_available,
    )
    monkeypatch.setattr("app.adapters.robot.RobotAdapter.home", home)

    create_orchestrator(db_path=str(tmp_path / "test.db"))

    connect_first_available.assert_called_once()
    home.assert_called_once()


def test_create_orchestrator_reads_reachability_check_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NENABOT_REACHABILITY_CHECK", "0")

    connect_first_available = MagicMock(
        return_value=RobotResult(ok=False, error="no robot")
    )
    monkeypatch.setattr(
        "app.adapters.robot.RobotAdapter.connect_first_available",
        connect_first_available,
    )

    orchestrator = create_orchestrator(db_path=str(tmp_path / "test.db"))

    assert orchestrator.reachability_check_enabled is False
    assert orchestrator._robot.reachability_check_enabled is False


def test_create_orchestrator_uses_mock_adapters_when_mock_mode_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NENABOT_MOCK_MODE", "1")
    monkeypatch.setenv("NENABOT_ENABLE_STARTUP_HOMING", "0")
    database_ctor = MagicMock(side_effect=AssertionError("Database should not be used"))
    monkeypatch.setattr("app.dependencies.Database", database_ctor)

    orchestrator = create_orchestrator(
        db_path=str(tmp_path / "test.db"),
    )

    assert isinstance(orchestrator._camera_vision, MockCameraVisionAdapter)
    assert isinstance(orchestrator._robot, MockRobotAdapter)
    assert isinstance(orchestrator._ionvision, MockIVAdapter)
    assert isinstance(orchestrator._storage, InMemoryStorageAdapter)
    database_ctor.assert_not_called()

    health = orchestrator.health()
    assert health["robot"]["status"] == "connected"
    assert health["camera"]["status"] == "connected"
    assert health["ionvision"]["status"] == "connected"
    assert orchestrator.is_calibrated is True

    ionvision = orchestrator._ionvision
    ping_payload = ionvision.ping().payload or {}
    assert "parameter" in ping_payload
    assert "id" in ping_payload["parameter"]
    assert "name" in ping_payload["parameter"]

    start_payload = ionvision.start_new_scan().payload or {}
    assert "message" in start_payload

    current_scan_payload = ionvision.get_current_scan().payload or {}
    assert "progress" in current_scan_payload
    assert "information" in current_scan_payload
    assert "state" in current_scan_payload

    # Mock scan should quickly move to finished and produce latest dataobject payload.
    time.sleep(1.1)
    finished_scan_payload = ionvision.get_current_scan().payload or {}
    assert finished_scan_payload.get("state") == "finished"

    latest_payload = ionvision.get_latest_dataobject().payload or {}
    assert "Id" in latest_payload
    assert "FinishTime" in latest_payload
    assert "results" in latest_payload
    assert "intensity_average" in latest_payload
    assert latest_payload["intensity_average"] > 0


def test_mock_mode_job_measurement_uses_realistic_ionvision_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NENABOT_MOCK_MODE", "1")

    orchestrator = create_orchestrator(
        db_path=str(tmp_path / "test.db"),
    )

    asyncio.run(orchestrator.initialize_ionvision())
    try:
        job = orchestrator.create_job(
            path=[Waypoint(x=200.0, y=100.0, z=-20.0, r=0.0)],
            dry_run=False,
        )

        orchestrator.run_job(job.id)

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            current = orchestrator.get_job(job.id)
            assert current is not None
            if current.state in {"completed", "failed", "stopped"}:
                break
            time.sleep(0.05)

        current = orchestrator.get_job(job.id)
        assert current is not None
        assert current.state == "completed"
        assert len(current.measurements) == 1

        measurement = current.measurements[0]
        assert measurement.simulated is False
        scan_result = measurement.scan_result
        assert isinstance(scan_result, dict)
        assert "Id" in scan_result
        assert "id" in scan_result
        assert "StartTime" in scan_result
        assert "FinishTime" in scan_result
        assert "SystemData" in scan_result
        assert "MeasurementData" in scan_result
        assert "gasDetection" in scan_result
        assert "evaluation" in scan_result
        assert "intensity_average" in scan_result
        assert scan_result["gasDetection"]["gasName"] == "ethanol"
        assert scan_result["evaluation"]["intensity_average"] > 0
    finally:
        asyncio.run(orchestrator.close_ionvision())


def test_mock_mode_job_has_scan_for_each_waypoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NENABOT_MOCK_MODE", "1")

    orchestrator = create_orchestrator(
        db_path=str(tmp_path / "test.db"),
    )

    asyncio.run(orchestrator.initialize_ionvision())
    try:
        job = orchestrator.create_job(
            path=[
                Waypoint(x=200.0, y=100.0, z=-20.0, r=0.0),
                Waypoint(x=205.0, y=102.0, z=-20.0, r=0.0),
            ],
            dry_run=False,
        )

        orchestrator.run_job(job.id)

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            current = orchestrator.get_job(job.id)
            assert current is not None
            if current.state in {"completed", "failed", "stopped"}:
                break
            time.sleep(0.05)

        current = orchestrator.get_job(job.id)
        assert current is not None
        assert current.state == "completed"
        assert len(current.measurements) == 2

        scan_ids: list[str] = []
        for measurement in current.measurements:
            assert measurement.simulated is False
            scan_result = measurement.scan_result
            assert isinstance(scan_result, dict)
            assert "scanId" in scan_result
            assert "evaluation" in scan_result
            assert scan_result["evaluation"]["intensity_average"] > 0
            scan_ids.append(str(scan_result["scanId"]))

        assert len(set(scan_ids)) == 2
    finally:
        asyncio.run(orchestrator.close_ionvision())


def test_mock_mode_uses_example_mapping_path_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NENABOT_MOCK_MODE", "1")
    monkeypatch.delenv("NENABOT_MAPPING_PATH", raising=False)
    monkeypatch.delenv("NENABOT_INTRINSICS_PATH", raising=False)

    orchestrator = create_orchestrator(db_path=":memory:")
    assert (
        str(orchestrator._mapping_path) == "data/calibration/robot_mapping.json.example"
    )
    assert (
        orchestrator._camera_vision.intrinsics_path
        == "data/calibration/camera_params.json"
    )
    assert orchestrator.is_calibrated is True
