from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
