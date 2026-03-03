from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add the vendored Dobot SDK (lib/dobot/) to sys.path so
# `import DobotDllTypeMulti` resolves regardless of cwd.
_DOBOT_LIB = str(Path(__file__).resolve().parents[2] / "lib" / "dobot")
if _DOBOT_LIB not in sys.path:
    sys.path.insert(0, _DOBOT_LIB)


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


class RobotAdapter:
    """
    Wrapper around Dobot DLL. Based on DobotDemoForPython/minimal_connect.py and DobotControl.py.
    """

    def __init__(self, baud: int = 115200) -> None:
        self._baud = baud
        self._api = None
        self._connected_port: Optional[str] = None

    def connect_first_available(self) -> RobotResult:
        try:
            import glob
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        self._api = dType.load()
        ports = sorted(glob.glob("/dev/cu.usbserial-*"))
        for port in ports:
            state = dType.ConnectDobot(self._api, port, self._baud)[0]
            if state == dType.DobotConnect.DobotConnect_NoError:
                self._connected_port = port
                return RobotResult(True)

        return RobotResult(False, "No Dobot device found")

    @property
    def connected(self) -> bool:
        return self._api is not None and self._connected_port is not None

    def move(self, x: float, y: float, z: float, r: float) -> RobotResult:
        if not self.connected:
            return RobotResult(False, "Not connected")

        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        dType.SetQueuedCmdStartExec(self._api)
        dType.SetPTPCmd(self._api, dType.PTPMode.PTPMOVLXYZMode, x, y, z, r, isQueued=1)
        return RobotResult(True)

    def home(self) -> RobotResult:
        if not self.connected:
            return RobotResult(False, "Not connected")
        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        dType.SetHOMECmd(self._api, temp=0, isQueued=1)
        return RobotResult(True)

    def stop(self) -> RobotResult:
        if not self.connected:
            return RobotResult(False, "Not connected")
        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        dType.SetQueuedCmdStopExec(self._api)
        return RobotResult(True)

    def get_pose(self) -> PoseResult:
        """Read the current Cartesian + joint pose from the robot arm."""
        if not self.connected:
            return PoseResult(ok=False, error="Not connected")
        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return PoseResult(ok=False, error=f"Dobot DLL not available: {exc}")
        try:
            pose = dType.GetPose(self._api)  # (x, y, z, r, j1, j2, j3, j4)
            return PoseResult(
                ok=True,
                x=float(pose[0]),
                y=float(pose[1]),
                z=float(pose[2]),
                r=float(pose[3]),
                j1=float(pose[4]),
                j2=float(pose[5]),
                j3=float(pose[6]),
                j4=float(pose[7]),
            )
        except Exception as exc:
            return PoseResult(ok=False, error=f"GetPose failed: {exc}")

    def disconnect(self) -> None:
        if not self._api:
            return
        try:
            import DobotDllTypeMulti as dType
            dType.DisconnectDobot(self._api)
        except Exception:
            # Ignore errors during disconnect - best-effort cleanup
            pass
        self._api = None
        self._connected_port = None
