from __future__ import annotations

import glob
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


def _get_dobot_dll_type():
    """Resolve Dobot wrapper, preferring test monkeypatches in app.adapters."""
    try:
        import app.adapters as adapters_module

        if hasattr(adapters_module, "DobotDllType"):
            return adapters_module.DobotDllType
    except Exception:
        pass

    from lib.dobot import DobotDllType

    return DobotDllType


@dataclass
class RobotResult:
    ok: bool
    error: Optional[str] = None


@dataclass
class PoseResult:
    ok: bool
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    r: float = 0.0
    j1: float = 0.0
    j2: float = 0.0
    j3: float = 0.0
    j4: float = 0.0
    error: Optional[str] = None


@dataclass
class RobotPose:
    x: float
    y: float
    z: float
    r: float
    joint1: float
    joint2: float
    joint3: float
    joint4: float


class RobotAdapter:
    """
    Wrapper around Dobot DLL.
    Based on DobotDemoForPython/minimal_connect.py and DobotControl.py.

    The adapter does NOT connect automatically on construction.
    Call ``connect_first_available()`` (auto-detect port) or pass a port
    explicitly to ``connect()`` before sending movement commands.
    """

    HOME_POSITION = (250, 0, 0, 0)
    COMMAND_TIMEOUT_S = 20.0
    LEGACY_HOMING_ENV = "DOBOT_ENABLE_LEGACY_HOMING"

    def __init__(self, baud: int = 115200) -> None:
        self._baud = baud
        self._connected_port: Optional[str] = None
        self._api = None

    # ---- connection helpers ----

    def _list_candidate_ports(self) -> list[str]:
        """Best-effort serial port discovery without extra dependencies."""
        if sys.platform.startswith("win"):
            try:
                import winreg
            except Exception:
                return []

            ports: list[str] = []
            key_path = r"HARDWARE\DEVICEMAP\SERIALCOMM"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    index = 0
                    while True:
                        try:
                            _, port, _ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        if isinstance(port, str) and port.upper().startswith("COM"):
                            ports.append(port)
                        index += 1
            except OSError:
                pass

            return sorted(set(ports))

        patterns: list[str] = []
        if sys.platform == "darwin":
            patterns = [
                "/dev/cu.usbserial-*",
                "/dev/tty.usbserial-*",
                "/dev/cu.usbmodem*",
                "/dev/tty.usbmodem*",
            ]
        else:
            patterns = [
                "/dev/ttyUSB*",
                "/dev/ttyACM*",
                "/dev/tty.usbserial-*",
                "/dev/cu.usbserial-*",
            ]

        ports: list[str] = []
        for pattern in patterns:
            ports.extend(glob.glob(pattern))
        return sorted(set(ports))

    def connect(self, port: str) -> RobotResult:
        """Connect to a Dobot on a specific serial port."""
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        self._api = DobotDllType.load()
        ret = DobotDllType.ConnectDobot(self._api, port, self._baud)[0]
        if ret == 0:
            if hasattr(DobotDllType, "SetCmdTimeout"):
                DobotDllType.SetCmdTimeout(self._api, int(self.COMMAND_TIMEOUT_S * 1000))
            if hasattr(DobotDllType, "SetQueuedCmdClear"):
                DobotDllType.SetQueuedCmdClear(self._api)
            if hasattr(DobotDllType, "SetQueuedCmdStartExec"):
                DobotDllType.SetQueuedCmdStartExec(self._api)
            self._connected_port = port
            print(f"Connected to Dobot on {port}")
            return RobotResult(True)
        return RobotResult(False, f"Failed to connect on {port}, error code: {ret}")

    def connect_first_available(self) -> RobotResult:
        """Auto-detect serial ports and connect to the first Dobot found."""
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        self._api = DobotDllType.load()
        ports = self._list_candidate_ports()
        for port in ports:
            ret = DobotDllType.ConnectDobot(self._api, port, self._baud)[0]
            if ret == 0:
                if hasattr(DobotDllType, "SetCmdTimeout"):
                    DobotDllType.SetCmdTimeout(self._api, int(self.COMMAND_TIMEOUT_S * 1000))
                if hasattr(DobotDllType, "SetQueuedCmdClear"):
                    DobotDllType.SetQueuedCmdClear(self._api)
                if hasattr(DobotDllType, "SetQueuedCmdStartExec"):
                    DobotDllType.SetQueuedCmdStartExec(self._api)
                self._connected_port = port
                print(f"Connected to Dobot on {port}")
                return RobotResult(True)

        if not ports:
            return RobotResult(
                False,
                "No serial ports detected (Windows: expected COMx; macOS/Linux: expected /dev/*)",
            )
        return RobotResult(False, "No Dobot device found")

    # ---- movement ----

    def _run_with_timeout(self, fn, timeout_s: float) -> RobotResult:
        done = threading.Event()
        failure: list[Exception] = []

        def _runner() -> None:
            try:
                fn()
            except Exception as exc:
                failure.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        if not done.wait(timeout=max(timeout_s, 0.1)):
            return RobotResult(False, f"Command timed out after {timeout_s:.1f}s")
        if failure:
            return RobotResult(False, str(failure[0]))
        return RobotResult(True)

    def move_to_coordinates(self, coords: Tuple[float, float, float, float], wait: bool = True) -> RobotResult:
        """Move robot to (x, y, z, r). If wait=True, blocks until the move finishes."""
        if self._api is None:
            return RobotResult(ok=False, error="No Dobot connection")
        try:
            DobotDllType = _get_dobot_dll_type()
            x, y, z, r = coords
            print(f"Moving to: {coords}")

            def _do_move() -> None:
                if hasattr(DobotDllType, "SetPTPCmdEx") and wait:
                    DobotDllType.SetPTPCmdEx(self._api, 1, x, y, z, r, 1)
                else:
                    DobotDllType.SetPTPCmd(self._api, 1, x, y, z, r, 0 if wait else 1)

            timeout_s = self.COMMAND_TIMEOUT_S if wait else 5.0
            return self._run_with_timeout(_do_move, timeout_s)
        except Exception as e:
            return RobotResult(ok=False, error=str(e))

    def execute_route(self, coordinates: List[Tuple[float, float, float, float]]) -> RobotResult:
        """
        Execute a sequence of moves and return home afterwards.

        Parameters
        ----------
        coordinates : list of (x, y, z, r) tuples
            The waypoints the robot should visit in order.
        """
        for coord in coordinates:
            result = self.move_to_coordinates(coord)
            if not result.ok:
                print(f"Error moving to {coord}: {result.error}")
                return result
            print(f"Moved to {coord}")

        # Return home
        home_result = self.home()
        if not home_result.ok:
            print(f"Error returning home: {home_result.error}")
            return home_result
        print(f"Returned to home position {self.HOME_POSITION}")
        return RobotResult(ok=True)

    def get_pose(self) -> tuple[RobotPose | None, RobotResult]:
        """Read the robot's current pose (x, y, z, r) and joint angles.

        Returns (pose, result). If result.ok is False, pose is None.
        """
        if self._api is None:
            return None, RobotResult(ok=False, error="No Dobot connection")
        try:
            DobotDllType = _get_dobot_dll_type()

            x, y, z, r, j1, j2, j3, j4 = DobotDllType.GetPose(self._api)
            if all(abs(value) < 1e-6 for value in (x, y, z, r, j1, j2, j3, j4)):
                return None, RobotResult(ok=False, error="GetPose returned all-zero values")
            return RobotPose(x=x, y=y, z=z, r=r, joint1=j1, joint2=j2, joint3=j3, joint4=j4), RobotResult(ok=True)
        except Exception as exc:
            return None, RobotResult(ok=False, error=str(exc))

    def homing(self, timeout_s: float = 30.0) -> RobotResult:
        """Run the Dobot's built-in homing routine (calibration and move to home position) (blocks until finished)."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        if hasattr(DobotDllType, "SetHOMECmdEx"):
            # Preferred path on newer wrappers: safer and supports blocking behavior.
            return self._run_with_timeout(
                lambda: DobotDllType.SetHOMECmdEx(self._api, 0, 1),
                timeout_s,
            )

        if hasattr(DobotDllType, "SetHOMECmd"):
            enable_legacy_homing = os.getenv(self.LEGACY_HOMING_ENV, "0") == "1"
            if enable_legacy_homing:
                # Legacy SetHOMECmd has been observed to crash some Windows setups.
                # Keep it available for environments where it is known to be stable.
                DobotDllType.SetHOMECmd(self._api, 0, 0)
                return RobotResult(True)

            # Safe default: avoid hard process crashes and move to configured home position.
            return self.home()

        return RobotResult(True)

    # Move to defined home position
    def home(self) -> RobotResult:
        """Move to HOME_POSITION using PTP (blocks until finished)."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        def _do_home() -> None:
            if hasattr(DobotDllType, "SetPTPCmdEx"):
                DobotDllType.SetPTPCmdEx(self._api, 1, *self.HOME_POSITION, 1)
            else:
                DobotDllType.SetPTPCmd(self._api, 1, *self.HOME_POSITION, 0)

        return self._run_with_timeout(_do_home, self.COMMAND_TIMEOUT_S)

    def pause(self) -> RobotResult:
        """Pause the command queue. Queued commands are preserved and can be resumed."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        DobotDllType.SetQueuedCmdStopExec(self._api)
        return RobotResult(True)

    def resume(self) -> RobotResult:
        """Resume executing the command queue after a pause."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        DobotDllType.SetQueuedCmdStartExec(self._api)
        return RobotResult(True)

    def stop(self) -> RobotResult:
        """Stop and clear the command queue. Use pause()/resume() to preserve queued commands."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        DobotDllType.SetQueuedCmdStopExec(self._api)
        DobotDllType.SetQueuedCmdClear(self._api)
        DobotDllType.SetQueuedCmdStartExec(self._api)
        return RobotResult(True)

    def wait_until_queue_empty(self, timeout_s: float = 10.0, poll_interval_s: float = 0.05) -> RobotResult:
        """Block until the queued command execution finishes or timeout is reached."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        if not hasattr(DobotDllType, "GetQueuedCmdMotionFinish"):
            return RobotResult(True)

        deadline = time.monotonic() + max(timeout_s, 0.0)
        while time.monotonic() <= deadline:
            try:
                finished_raw = DobotDllType.GetQueuedCmdMotionFinish(self._api)
                finished = bool(finished_raw[0]) if isinstance(finished_raw, (tuple, list)) else bool(finished_raw)
                if finished:
                    return RobotResult(True)
            except Exception as exc:
                return RobotResult(False, str(exc))

            if poll_interval_s > 0:
                time.sleep(poll_interval_s)

        return RobotResult(False, "Timed out waiting for queue to finish")

    # ---- cleanup ----

    def disconnect(self) -> None:
        if not self._api:
            return
        try:
            DobotDllType = _get_dobot_dll_type()
            DobotDllType.DisconnectDobot(self._api)
            print("Disconnected Dobot")
        except Exception:
            pass
        self._api = None
        self._connected_port = None
