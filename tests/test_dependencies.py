from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.adapters.memory_storage import InMemoryStorageAdapter
from app.adapters.mock_camera_vision import MockCameraVisionAdapter
from app.adapters.mock_ionVision import MockIVAdapter
from app.adapters.mock_robot import MockRobotAdapter
from app.adapters.robot import RobotResult
from app.dependencies import create_orchestrator


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


def test_create_orchestrator_uses_mock_adapters_when_mock_mode_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("NENABOT_MOCK_MODE", "1")
    monkeypatch.setenv("NENABOT_ENABLE_STARTUP_HOMING", "0")
    database_ctor = MagicMock(side_effect=AssertionError("Database should not be used"))
    monkeypatch.setattr("app.dependencies.Database", database_ctor)

    orchestrator = create_orchestrator(
        db_path=str(tmp_path / "test.db"),
        intrinsics_path=str(tmp_path / "mock_intrinsics.json"),
        mapping_path=str(tmp_path / "mock_mapping.json"),
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
