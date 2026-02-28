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

    # def connect_first_available(self) -> RobotResult:
    #     try:
    #         import glob
    #         import DobotDllTypeMulti as dType
    #     except Exception as exc:  # pragma: no cover - hardware dependency
    #         return RobotResult(False, f"Dobot DLL not available: {exc}")

    #     self._api = dType.load()
    #     # For MAC users, the Dobot typically shows up as /dev/cu.usbserial-*
    #     ports = sorted(glob.glob("/dev/cu.usbserial-*"))
        
    #     for port in ports:
    #         state = dType.ConnectDobot(self._api, port, self._baud)[0]
    #         if state == dType.DobotConnect.DobotConnect_NoError:
    #             self._connected_port = port
    #             return RobotResult(True)

    #     return RobotResult(False, "No Dobot device found")
    
    def connect_first_available(self) -> RobotResult:
        try:
            import DobotDllType as dType
            import sys
            import glob
        except Exception as exc:  # pragma: no cover
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        self._api = dType.load()
        
        # Determine the correct "wiring" for the operating system
        
        # Determine the correct "wiring" for the operating system
        if sys.platform.startswith('win'):
            # HARDWIRED FOR TESTING: Only check COM5
            ports = ['COM5'] 
        else:
            # macOS / Linux
            ports = sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/ttyUSB*"))

        for port in ports:
            # The DLL often expects strings, but we suppress errors for closed ports
            state = dType.ConnectDobot(self._api, port, self._baud)[0]
            if state == dType.DobotConnect.DobotConnect_NoError:
                self._connected_port = port
                return RobotResult(True)

        return RobotResult(False, "No Dobot device found on scanned ports")

    def move(self, x: float, y: float, z: float, r: float) -> RobotResult:
        if not self._api:
            return RobotResult(False, "Not connected")

        try:
            import DobotDllType as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")

        dType.SetQueuedCmdStartExec(self._api)
        dType.SetPTPCmd(self._api, dType.PTPMode.PTPMOVLXYZMode, x, y, z, r, isQueued=1)
        return RobotResult(True)

    def home(self) -> RobotResult:
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            import DobotDllType as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        dType.SetHOMECmd(self._api, temp=0, isQueued=1)
        return RobotResult(True)

    def stop(self) -> RobotResult:
        if not self._api:
            return RobotResult(False, "Not connected")
        try:
            import DobotDllType as dType
        except Exception as exc:  # pragma: no cover - hardware dependency
            return RobotResult(False, f"Dobot DLL not available: {exc}")
        dType.SetQueuedCmdStopExec(self._api)
        return RobotResult(True)

    def disconnect(self) -> None:
        if not self._api:
            return
        try:
            import DobotDllType as dType
            dType.DisconnectDobot(self._api)
        except Exception:
            # Ignore errors during disconnect - best-effort cleanup
            pass
        self._api = None
        self._connected_port = None

    # NEw: Add a method to read the current pose of the robot arm
    def get_pose(self) -> tuple[float, float, float]:
            """Ask the motors for their current X, Y, Z coordinates."""
            if not self._api:
                return 0.0, 0.0, 0.0
                
            try:
                import DobotDllTypeMulti as dType
                # The robot returns a list of 8 numbers. The first 3 are X, Y, and Z.
                pose = dType.GetPose(self._api)
                return float(pose[0]), float(pose[1]), float(pose[2])
            except Exception as exc:
                print(f"Failed to read pose: {exc}")
                return 0.0, 0.0, 0.0