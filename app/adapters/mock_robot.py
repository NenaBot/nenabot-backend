from __future__ import annotations

from app.adapters.robot import PoseResult, RobotResult


class MockRobotAdapter:
    """In-memory robot adapter for frontend/dev mock mode."""

    def __init__(self) -> None:
        self._connected = False
        self._pose = PoseResult(ok=True, x=200.0, y=100.0, z=-50.0, r=0.0)

    def connect(self, port: str) -> RobotResult:
        self._connected = True
        return RobotResult(ok=True)

    def connect_first_available(self) -> RobotResult:
        self._connected = True
        return RobotResult(ok=True)

    def ping(self) -> RobotResult:
        if not self._connected:
            return RobotResult(ok=False, error="Mock robot not connected")
        return RobotResult(ok=True)

    def move_to_coordinates(
        self, coords: tuple[float, float, float, float], wait: bool = True
    ) -> RobotResult:
        x, y, z, r = coords
        return self.move(x, y, z, r, wait=wait)

    def move(
        self, x: float, y: float, z: float, r: float, wait: bool = True
    ) -> RobotResult:
        self._pose = PoseResult(ok=True, x=x, y=y, z=z, r=r)
        return RobotResult(ok=True)

    def execute_route(self, coordinates: list[tuple[float, float, float, float]]) -> RobotResult:
        for x, y, z, r in coordinates:
            result = self.move(x, y, z, r, wait=True)
            if not result.ok:
                return result
        return RobotResult(ok=True)

    def get_pose(self) -> PoseResult:
        if not self._connected:
            return PoseResult(ok=False, error="Mock robot not connected")
        return self._pose

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
        self._pose = PoseResult(ok=True, x=x, y=y, z=z, r=r)
        return self._pose

    def home(self) -> RobotResult:
        self._pose = PoseResult(ok=True, x=200.0, y=100.0, z=-50.0, r=0.0)
        return RobotResult(ok=True)

    def homing(self) -> RobotResult:
        return self.home()

    def pause(self) -> RobotResult:
        return RobotResult(ok=True)

    def resume(self) -> RobotResult:
        return RobotResult(ok=True)

    def stop(self) -> RobotResult:
        return RobotResult(ok=True)

    def wait_until_queue_empty(
        self, timeout_s: float = 10.0, poll_interval_s: float = 0.05
    ) -> RobotResult:
        return RobotResult(ok=True)

    def disconnect(self) -> None:
        self._connected = False
