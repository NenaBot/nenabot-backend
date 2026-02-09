from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RobotResult:
    ok: bool
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

    def move(self, x: float, y: float, z: float, r: float) -> RobotResult:
        if not self._api:
            return RobotResult(False, "Not connected")

        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        dType.SetQueuedCmdStartExec(self._api)
        dType.SetPTPCmd(self._api, dType.PTPMode.PTPMOVLXYZMode, x, y, z, r, isQueued=1)
        return RobotResult(True)

    def home(self) -> RobotResult:
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        dType.SetHOMECmd(self._api, temp=0, isQueued=1)
        return RobotResult(True)

    def stop(self) -> RobotResult:
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            import DobotDllTypeMulti as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        dType.SetQueuedCmdStopExec(self._api)
        return RobotResult(True)

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
