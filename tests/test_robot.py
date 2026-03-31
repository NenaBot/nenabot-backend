import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from app.adapters.robot import RobotAdapter


USE_BUILTIN_HOMING = os.getenv("DOBOT_USE_BUILTIN_HOMING", "0") == "1"
DEFAULT_WINDOWS_PORT = os.getenv("DOBOT_PORT", "COM3")
ENABLE_AUTODETECT_FALLBACK = os.getenv("DOBOT_ENABLE_AUTODETECT", "0") == "1"


def connect_robot(adapter: RobotAdapter):
    """Connect with a fast Windows-first strategy to avoid auto-detect hangs."""
    print("\n--- Connecting to Dobot ---")

    if sys.platform.startswith("win"):
        if DEFAULT_WINDOWS_PORT:
            print(f"Trying direct port first: {DEFAULT_WINDOWS_PORT}")
            direct_result = adapter.connect(DEFAULT_WINDOWS_PORT)
            if direct_result.ok:
                print(f"Connected on {DEFAULT_WINDOWS_PORT}!")
                return direct_result
            if not ENABLE_AUTODETECT_FALLBACK:
                return direct_result
            print(f"Direct connect failed ({direct_result.error}), trying auto-detect...")
        elif not ENABLE_AUTODETECT_FALLBACK:
            return type("ConnectResult", (), {
                "ok": False,
                "error": "Set DOBOT_PORT (for example COM3) or enable DOBOT_ENABLE_AUTODETECT=1",
            })()

    auto_result = adapter.connect_first_available()
    if auto_result.ok:
        print("Connected via auto-detect!")
    return auto_result


def move_to_start_position(adapter: RobotAdapter) -> None:
    """Use safe home move by default; enable built-in homing only when requested."""
    if USE_BUILTIN_HOMING:
        print("--- Running built-in homing routine ---")
        result = adapter.homing()
        assert result.ok is True, f"Homing failed: {result.error}"
        print("Homing complete!")
        return

    print("--- Moving to home position (safe mode, homing disabled) ---")
    result = adapter.home()
    assert result.ok is True, f"Home failed: {result.error}"
    print("At home position!")


def test_live_hardware_route():
    """
    Connect to the Dobot, run a rectangular route, and return home.
    Make sure the robot is powered on and connected via USB before running!
    """
    adapter = RobotAdapter()

    # --- 1. Connect ---
    connect_result = connect_robot(adapter)

    assert connect_result.ok is True, f"Connection failed: {connect_result.error}"
    print("Connected!")

    # --- 2. Move to start position ---
    move_to_start_position(adapter)

    # --- 3. Execute route ---
    coordinates = [
        (300, 0, 0, 0),
        (304, 40, -40, 0),
        (201, 40, -40, 0),
        (201, -40, -40, 0),
    ]

    print(f"--- Running route with {len(coordinates)} waypoints ---")
    route_result = adapter.execute_route(coordinates)
    assert route_result.ok is True, f"Route failed: {route_result.error}"
    print("Route completed and robot returned home!")

    # --- 4. Return to home ---
    print("--- Returning to home position ---")
    home_result = adapter.home()
    assert home_result.ok is True, f"Return home failed: {home_result.error}"
    print("Back at home position!")

    # --- 5. Disconnect ---
    adapter.disconnect()
    print("Disconnected. Test passed!")


def test_stop_command_queue():
    """
    Connect to the Dobot, start a long route, then stop the command queue
    mid-execution. Verifies that stop() halts queued movements.
    """
    adapter = RobotAdapter()

    # --- 1. Connect ---
    connect_result = connect_robot(adapter)

    assert connect_result.ok is True, f"Connection failed: {connect_result.error}"
    print("Connected!")

    # --- 2. Queue several waypoints ---
    coordinates = [
        (300, 0, 0, 0),
        (304, 40, -30, 0),
        (201, 40, -30, 0),
        (201, -40, -30, 0),
    ]

    print(f"--- Queuing {len(coordinates)} waypoints ---")
    for coord in coordinates:
        result = adapter.move_to_coordinates(coord, wait=False)
        assert result.ok is True, f"Failed to queue {coord}: {result.error}"
        print(f"Queued: {coord}")

    # --- 3. Stop the command queue ---
    print("--- Stopping command queue ---")
    stop_result = adapter.stop()
    assert stop_result.ok is True, f"Stop failed: {stop_result.error}"
    print("Command queue stopped!")

    # --- 4. Disconnect ---
    adapter.disconnect()
    print("Disconnected. Stop-test passed!")


def test_pause_and_resume_route():
    """
    Connect to the Dobot, queue a route, pause mid-execution,
    then resume and let the route finish.
    """
    import time
    adapter = RobotAdapter()

    # --- 1. Connect ---
    connect_result = connect_robot(adapter)

    assert connect_result.ok is True, f"Connection failed: {connect_result.error}"
    print("Connected!")

    # --- 2. Go to home position ---
    print("--- Moving to home position ---")
    home_result = adapter.home()
    assert home_result.ok is True, f"Home failed: {home_result.error}"
    print("At home position!")

    # --- 3. Queue waypoints (non-blocking) ---
    coordinates = [
        (304, -40, -30, 0),
        (304, 40, -30, 0),
        (201, 40, -30, 0),
        (201, -40, -30, 0),
    ]

    print(f"--- Queuing {len(coordinates)} waypoints ---")
    for coord in coordinates:
        result = adapter.move_to_coordinates(coord, wait=False)
        assert result.ok is True, f"Failed to queue {coord}: {result.error}"
        print(f"Queued: {coord}")

    # --- 3. Let the robot start moving, then pause ---
    print("--- Waiting 2 s then pausing ---")
    time.sleep(2)
    pause_result = adapter.pause()
    assert pause_result.ok is True, f"Pause failed: {pause_result.error}"
    print("Route paused!")

    # --- 4. Wait a moment while paused ---
    print("--- Paused for 3 s ---")
    time.sleep(3)

    # --- 5. Resume the route ---
    print("--- Resuming route ---")
    resume_result = adapter.resume()
    assert resume_result.ok is True, f"Resume failed: {resume_result.error}"
    print("Route resumed!")

    # --- 6. Wait for route to finish ---
    print("--- Waiting for route to complete ---")
    wait_result = adapter.wait_until_queue_empty(timeout_s=120.0, poll_interval_s=0.5)
    assert wait_result.ok is True, f"Waiting for route completion failed: {wait_result.error}"
    print("Route completed!")

    # --- 7. Return to home ---
    print("--- Returning to home position ---")
    home_result = adapter.home()
    assert home_result.ok is True, f"Return home failed: {home_result.error}"
    print("Back at home position!")

    # --- 8. Disconnect ---
    adapter.disconnect()
    print("Disconnected. Pause/resume test passed!")

