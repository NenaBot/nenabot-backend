import os
import sys
import time
from typing import Iterator

import pytest

from app.adapters.robot import RobotAdapter


RUN_HARDWARE_TESTS = os.getenv("RUN_ROBOT_HARDWARE_TESTS", "0") == "1"


def _rect_route() -> list[tuple[float, float, float, float]]:
    return [
        (304, -40, -30, 0),
        (304, 40, -30, 0),
        (201, 40, -30, 0),
        (201, -40, -30, 0),
    ]


@pytest.fixture
def connected_robot() -> Iterator[RobotAdapter]:
    if not RUN_HARDWARE_TESTS:
        pytest.skip("Set RUN_ROBOT_HARDWARE_TESTS=1 to run live Dobot tests")

    adapter = RobotAdapter()
    connect_result = adapter.connect_first_available()

    if not connect_result.ok and sys.platform.startswith("win"):
        connect_result = adapter.connect("COM3")

    if not connect_result.ok:
        pytest.skip(f"Dobot not available for tests: {connect_result.error}")

    try:
        yield adapter
    finally:
        adapter.disconnect()


def ensure_homing(adapter: RobotAdapter) -> None:
    homing_result = adapter.homing()
    assert homing_result.ok, f"Homing failed: {homing_result.error}"


def queue_route(
    adapter: RobotAdapter, coordinates: list[tuple[float, float, float, float]]
) -> None:
    for coord in coordinates:
        result = adapter.move_to_coordinates(coord, wait=False)
        assert result.ok, f"Failed to queue {coord}: {result.error}"


@pytest.mark.hardware
@pytest.mark.integration
def test_live_hardware_route(connected_robot: RobotAdapter):
    adapter = connected_robot
    ensure_homing(adapter)

    coordinates = _rect_route()
    route_result = adapter.execute_route(coordinates)
    assert route_result.ok, f"Route failed: {route_result.error}"

    home_result = adapter.home()
    assert home_result.ok, f"Return home failed: {home_result.error}"


@pytest.mark.hardware
@pytest.mark.integration
def test_stop_command_queue(connected_robot: RobotAdapter):
    adapter = connected_robot
    ensure_homing(adapter)

    queue_route(adapter, _rect_route())
    stop_result = adapter.stop()
    assert stop_result.ok, f"Stop failed: {stop_result.error}"


@pytest.mark.hardware
@pytest.mark.integration
def test_pause_and_resume_route(connected_robot: RobotAdapter):
    adapter = connected_robot
    ensure_homing(adapter)

    queue_route(adapter, _rect_route())

    time.sleep(2)
    pause_result = adapter.pause()
    assert pause_result.ok, f"Pause failed: {pause_result.error}"

    time.sleep(3)

    resume_result = adapter.resume()
    assert resume_result.ok, f"Resume failed: {resume_result.error}"

    done_result = adapter.wait_until_queue_empty(timeout_s=60.0)
    assert done_result.ok, f"Route did not complete: {done_result.error}"

    home_result = adapter.home()
    assert home_result.ok, f"Return home failed: {home_result.error}"
