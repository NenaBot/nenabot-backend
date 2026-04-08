from __future__ import annotations

import glob
import logging
from math import sqrt
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

def _get_dobot_dll_type():
    if sys.platform.startswith("win"):
        from lib.dobot import DobotDllType

        return DobotDllType

    from lib.dobot import Multi

    return Multi


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

    def __iter__(self):
        """Backward-compatible unpacking support: pose, result = get_pose()."""
        pose = None
        if self.ok:
            pose = RobotPose(
                x=self.x,
                y=self.y,
                z=self.z,
                r=self.r,
                joint1=self.j1,
                joint2=self.j2,
                joint3=self.j3,
                joint4=self.j4,
            )
        yield pose
        yield RobotResult(ok=self.ok, error=self.error)


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

    COMMAND_TIMEOUT_S = 20.0
    HOMING_TIMEOUT_S = 60.0
    LEGACY_HOMING_ENV = "DOBOT_ENABLE_LEGACY_HOMING"

    def __init__(self, baud: int = 115200) -> None:
        self._baud = baud
        self._connected_port: Optional[str] = None
        self._api = None

    # ---- connection helpers ----

    def _list_candidate_ports(self) -> list[str]:
        """Best-effort serial port discovery without extra dependencies."""
        def _port_sort_key(port: str) -> tuple[int, str]:
            match = re.fullmatch(r"COM(\d+)", port.upper())
            if match:
                return (int(match.group(1)), port.upper())
            return (10_000, port.upper())

        if sys.platform.startswith("win"):
            try:
                import winreg
            except Exception:
                return []

            ports: list[str] = []
            serial_key_path = r"HARDWARE\DEVICEMAP\SERIALCOMM"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, serial_key_path) as key:
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

            # Fallback source for machines where SERIALCOMM is incomplete.
            ports_key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Ports"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ports_key_path) as key:
                    index = 0
                    while True:
                        try:
                            value_name, value_data, _ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        for candidate in (value_name, value_data):
                            if not isinstance(candidate, str):
                                continue
                            candidate = candidate.rstrip(":").upper()
                            if re.fullmatch(r"COM\d+", candidate):
                                ports.append(candidate)
                        index += 1
            except OSError:
                pass

            return sorted(set(ports), key=_port_sort_key)

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

    def _iter_connection_port_candidates(self, port: str) -> list[str]:
        """Generate platform-specific port representations to maximize connect success."""
        candidates: list[str] = []

        normalized = (port or "").strip()
        if normalized:
            candidates.append(normalized)

        if sys.platform.startswith("win") and normalized.upper().startswith("COM"):
            # Some Windows stacks require the extended COM syntax for COM10+.
            extended = f"\\\\.\\{normalized.upper()}"
            if extended not in candidates:
                candidates.append(extended)

        return candidates

    def _finalize_connection(self, DobotDllType, port: str) -> RobotResult:
        if hasattr(DobotDllType, "SetCmdTimeout"):
            DobotDllType.SetCmdTimeout(self._api, int(self.COMMAND_TIMEOUT_S * 1000))
        if hasattr(DobotDllType, "SetQueuedCmdClear"):
            DobotDllType.SetQueuedCmdClear(self._api)
        if hasattr(DobotDllType, "SetQueuedCmdStartExec"):
            DobotDllType.SetQueuedCmdStartExec(self._api)
        self._connected_port = port
        print(f"Connected to Dobot on {port}")
        return RobotResult(True)

    def _connect_with_port_candidates(
        self, DobotDllType, requested_port: str
    ) -> tuple[Optional[str], Optional[int], list[tuple[str, int]]]:
        attempts: list[tuple[str, int]] = []
        for candidate in self._iter_connection_port_candidates(requested_port):
            try:
                ret = DobotDllType.ConnectDobot(self._api, candidate, self._baud)[0]
            except Exception:
                ret = -1
            attempts.append((candidate, ret))
            if ret == 0:
                return candidate, ret, attempts
        return None, None, attempts

    def connect(self, port: str) -> RobotResult:
        """Connect to a Dobot on a specific serial port."""
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        try:
            self._api = DobotDllType.load()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL load failed: {exc}")
        connected_port, _, attempts = self._connect_with_port_candidates(
            DobotDllType, port
        )
        if connected_port is not None:
            return self._finalize_connection(DobotDllType, connected_port)

        attempts_summary = ", ".join(f"{p}->{code}" for p, code in attempts)
        return RobotResult(
            False,
            f"Failed to connect on requested port {port}. Attempts: {attempts_summary}",
        )

    def connect_first_available(self) -> RobotResult:
        """Auto-detect serial ports and connect to the first Dobot found."""
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        try:
            self._api = DobotDllType.load()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL load failed: {exc}")
        ports = self._list_candidate_ports()
        failed_attempts: list[tuple[str, int]] = []
        for port in ports:
            connected_port, _, attempts = self._connect_with_port_candidates(
                DobotDllType, port
            )
            failed_attempts.extend(attempts)
            if connected_port is not None:
                return self._finalize_connection(DobotDllType, connected_port)

        if not ports:
            return RobotResult(
                False,
                "No serial ports detected (Windows: expected COMx; macOS/Linux: expected /dev/*)",
            )
        if failed_attempts:
            attempts_summary = ", ".join(
                f"{p}->{code}" for p, code in failed_attempts
            )
            return RobotResult(False, f"No Dobot device found. Attempts: {attempts_summary}")
        return RobotResult(False, "No Dobot device found")

    def ping(self) -> RobotResult:
        """Quick connectivity probe used by health checks."""
        if self._api is None:
            return RobotResult(False, "Not connected")
        return RobotResult(True)

    # ---- movement ----

    def move_to_coordinates(
        self, coords: Tuple[float, float, float, float], wait: bool = True
    ) -> RobotResult:
        """Move robot to (x, y, z, r). If wait=True, blocks until the move finishes."""
        if self._api is None:
            return RobotResult(ok=False, error="No Dobot connection")
        try:
            DobotDllType = _get_dobot_dll_type()
            x, y, z, r = coords
            print(f"Moving to: {coords}")
            if hasattr(DobotDllType, "SetPTPCmdEx") and wait:
                DobotDllType.SetPTPCmdEx(self._api, 1, x, y, z, r, 1)
            else:
                DobotDllType.SetPTPCmd(self._api, 1, x, y, z, r, 0 if wait else 1)
            return RobotResult(ok=True)
        except Exception as e:
            return RobotResult(ok=False, error=str(e))

    def move(
        self, x: float, y: float, z: float, r: float, wait: bool = True
    ) -> RobotResult:
        """Compatibility wrapper used by orchestrator/tests."""
        return self.move_to_coordinates((x, y, z, r), wait=wait)

    def execute_route(
        self, coordinates: List[Tuple[float, float, float, float]]
    ) -> RobotResult:
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
        print("Returned home")
        return RobotResult(ok=True)

    def get_pose(self) -> PoseResult:
        """Read the robot's current pose (x, y, z, r) and joint angles."""
        if self._api is None:
            return PoseResult(ok=False, error="No Dobot connection")
        try:
            DobotDllType = _get_dobot_dll_type()

            x, y, z, r, j1, j2, j3, j4 = DobotDllType.GetPose(self._api)
            if all(abs(value) < 1e-6 for value in (x, y, z, r, j1, j2, j3, j4)):
                return PoseResult(ok=False, error="GetPose returned all-zero values")
            return PoseResult(ok=True, x=x, y=y, z=z, r=r, j1=j1, j2=j2, j3=j3, j4=j4)
        except Exception as exc:
            return PoseResult(ok=False, error=str(exc))

    def wait_for_position(
        self,
        x: float,
        y: float,
        z: float,
        r: float,
        tolerance_mm: float = 1.0,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.05,
    ) -> PoseResult:
        """Wait until current Cartesian pose is within tolerance of target pose."""
        if self._api is None:
            return PoseResult(ok=False, error="No Dobot connection")

        tolerance = max(tolerance_mm, 0.0)
        deadline = time.monotonic() + max(timeout_s, 0.0)
        last_error: str | None = None

        while time.monotonic() <= deadline:
            pose = self.get_pose()
            if pose.ok:
                if (
                    abs(pose.x - x) <= tolerance
                    and abs(pose.y - y) <= tolerance
                    and abs(pose.z - z) <= tolerance
                    and abs(pose.r - r) <= tolerance
                ):
                    return pose
            else:
                last_error = pose.error

            if poll_interval_s > 0:
                time.sleep(poll_interval_s)

        timeout_error = "Timeout waiting for target pose"
        if last_error:
            timeout_error = f"{timeout_error}: {last_error}"
        return PoseResult(ok=False, error=timeout_error)

    def home(self) -> RobotResult:
        """Run the Dobot's built-in homing routine (blocks until finished)."""
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            DobotDllType = _get_dobot_dll_type()
        except Exception as exc:
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        if hasattr(DobotDllType, "SetHOMECmdEx"):
            DobotDllType.SetHOMECmdEx(self._api, 0, 1)
            return RobotResult(True)

        if hasattr(DobotDllType, "SetHOMECmd"):
            if (
                sys.platform.startswith("win")
                and os.getenv(self.LEGACY_HOMING_ENV, "0") != "1"
            ):
                # SetHOMECmd has been observed to crash some Windows setups.
                # Skip it on Windows unless explicitly opted in.
                logger.warning(
                    "Skipping SetHOMECmd on Windows — set DOBOT_ENABLE_LEGACY_HOMING=1 to enable."
                )
                return RobotResult(True)
            DobotDllType.SetHOMECmd(self._api, 0, 0)  # isQueued=0, fires immediately
            logger.info("Homing command sent, waiting for arm to finish...")
            return self._wait_for_motion_stop(timeout_s=self.HOMING_TIMEOUT_S)

        return RobotResult(True)

    def _wait_for_motion_stop(
        self,
        timeout_s: float = 60.0,
        stable_s: float = 1.5,
        poll_interval_s: float = 0.3,
        tolerance_mm: float = 0.5,
    ) -> RobotResult:
        """Poll GetPose until the arm position stops changing for stable_s seconds."""
        deadline = time.monotonic() + timeout_s
        last_x = last_y = last_z = None
        stable_since: float | None = None

        while time.monotonic() <= deadline:
            time.sleep(poll_interval_s)
            pose = self.get_pose()
            if not pose.ok:
                stable_since = None
                last_x = last_y = last_z = None
                continue

            if last_x is not None:
                moved = (
                    abs(pose.x - last_x) > tolerance_mm
                    or abs(pose.y - last_y) > tolerance_mm
                    or abs(pose.z - last_z) > tolerance_mm
                )
                if moved:
                    stable_since = None
                else:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= stable_s:
                        logger.info(
                            "Arm motion stopped at (%.1f, %.1f, %.1f)",
                            pose.x,
                            pose.y,
                            pose.z,
                        )
                        return RobotResult(True)

            last_x, last_y, last_z = pose.x, pose.y, pose.z

        return RobotResult(False, "Timeout waiting for arm motion to stop")

    def homing(self) -> RobotResult:
        """Alias for home(). Runs the Dobot's built-in homing routine."""
        return self.home()

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

    def wait_until_queue_empty(
        self, timeout_s: float = 10.0, poll_interval_s: float = 0.05
    ) -> RobotResult:
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
                finished = (
                    bool(finished_raw[0])
                    if isinstance(finished_raw, (tuple, list))
                    else bool(finished_raw)
                )
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

    def is_reachable_mm(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        """blahblah"""

        if(z_mm > 0 or z_mm < -30 or x_mm < 10):
            return False
        
        dist = sqrt(y_mm**2+x_mm**2)
        if dist > 320 or dist < 180:
            return False
        else:
            return True