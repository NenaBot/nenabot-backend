from __future__ import annotations

import types

import pytest

from app.adapters.robot import RobotAdapter


class FakeDobotDllType:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.connect_ret = 0
        self.motion_finish_sequence: list[bool] = [True]

    def load(self):
        self.calls.append(("load", ()))
        return object()

    def ConnectDobot(self, api, port, baud):
        self.calls.append(("ConnectDobot", (api, port, baud)))
        return (self.connect_ret,)

    def SetQueuedCmdClear(self, api):
        self.calls.append(("SetQueuedCmdClear", (api,)))

    def SetQueuedCmdStartExec(self, api):
        self.calls.append(("SetQueuedCmdStartExec", (api,)))

    def SetQueuedCmdStopExec(self, api):
        self.calls.append(("SetQueuedCmdStopExec", (api,)))

    def SetPTPCmdEx(self, api, mode, x, y, z, r, queued):
        self.calls.append(("SetPTPCmdEx", (api, mode, x, y, z, r, queued)))

    def SetPTPCmd(self, api, mode, x, y, z, r, queued):
        self.calls.append(("SetPTPCmd", (api, mode, x, y, z, r, queued)))

    def GetPose(self, api):
        self.calls.append(("GetPose", (api,)))
        return (1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0, 40.0)

    def SetHOMECmdEx(self, api, temp, queued):
        self.calls.append(("SetHOMECmdEx", (api, temp, queued)))

    def GetQueuedCmdMotionFinish(self, api):
        self.calls.append(("GetQueuedCmdMotionFinish", (api,)))
        if self.motion_finish_sequence:
            return (self.motion_finish_sequence.pop(0),)
        return (True,)

    def DisconnectDobot(self, api):
        self.calls.append(("DisconnectDobot", (api,)))


def _install_fake_dobot(monkeypatch: pytest.MonkeyPatch) -> FakeDobotDllType:
    fake = FakeDobotDllType()
    monkeypatch.setattr("app.adapters.robot._get_dobot_dll_type", lambda: fake)
    return fake


def test_connect_success_starts_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter()

    result = adapter.connect("COM7")

    assert result.ok is True
    assert [name for name, _ in fake.calls] == [
        "load",
        "ConnectDobot",
        "SetQueuedCmdClear",
        "SetQueuedCmdStartExec",
    ]


def test_connect_failure_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    fake.connect_ret = 2
    adapter = RobotAdapter()

    result = adapter.connect("COM7")

    assert result.ok is False
    assert "error code: 2" in (result.error or "")


def test_move_to_coordinates_requires_connection() -> None:
    adapter = RobotAdapter()

    result = adapter.move_to_coordinates((1, 2, 3, 4))

    assert result.ok is False
    assert result.error == "No Dobot connection"


def test_move_to_coordinates_wait_and_nonwait(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter()
    adapter._api = object()

    wait_result = adapter.move_to_coordinates((200, 20, -10, 40), wait=True)
    queue_result = adapter.move_to_coordinates((210, 20, -10, 41), wait=False)

    assert wait_result.ok is True
    assert queue_result.ok is True
    assert [name for name, _ in fake.calls] == ["SetPTPCmdEx", "SetPTPCmd"]


def test_move_to_coordinates_rejects_unreachable_without_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter()
    adapter._api = object()

    result = adapter.move_to_coordinates((5, 10, -10, 0), wait=True)

    assert result.ok is False
    assert "outside the reachable area" in (result.error or "")
    assert [name for name, _ in fake.calls] == []


def test_move_to_coordinates_allows_unreachable_when_check_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter(reachability_check_enabled=False)
    adapter._api = object()

    result = adapter.move_to_coordinates((5, 10, -10, 0), wait=True)

    assert result.ok is True
    assert [name for name, _ in fake.calls] == ["SetPTPCmdEx"]


def test_execute_route_moves_then_home(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RobotAdapter()

    called: list[tuple[str, tuple]] = []

    def fake_move(coords, wait=True):
        called.append(("move", (coords, wait)))
        return types.SimpleNamespace(ok=True, error=None)

    def fake_home():
        called.append(("home", ()))
        return types.SimpleNamespace(ok=True, error=None)

    monkeypatch.setattr(adapter, "move_to_coordinates", fake_move)
    monkeypatch.setattr(adapter, "home", fake_home)

    result = adapter.execute_route([(1, 2, 3, 4), (5, 6, 7, 8)])

    assert result.ok is True
    assert called == [
        ("move", ((1, 2, 3, 4), True)),
        ("move", ((5, 6, 7, 8), True)),
        ("home", ()),
    ]


def test_get_pose_maps_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter()
    adapter._api = object()

    pose, result = adapter.get_pose()

    assert result.ok is True
    assert pose is not None
    assert (pose.x, pose.y, pose.z, pose.r) == (1.0, 2.0, 3.0, 4.0)
    assert (pose.joint1, pose.joint2, pose.joint3, pose.joint4) == (
        10.0,
        20.0,
        30.0,
        40.0,
    )


def test_pause_resume_stop_call_expected_dll(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter()
    adapter._api = object()

    pause_result = adapter.pause()
    resume_result = adapter.resume()
    stop_result = adapter.stop()

    assert pause_result.ok is True
    assert resume_result.ok is True
    assert stop_result.ok is True
    assert [name for name, _ in fake.calls] == [
        "SetQueuedCmdStopExec",
        "SetQueuedCmdStartExec",
        "SetQueuedCmdStopExec",
        "SetQueuedCmdClear",
        "SetQueuedCmdStartExec",
    ]


def test_wait_until_queue_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    fake.motion_finish_sequence = [False, False, True]
    adapter = RobotAdapter()
    adapter._api = object()

    result = adapter.wait_until_queue_empty(timeout_s=0.2, poll_interval_s=0.0)

    assert result.ok is True


def test_wait_until_queue_empty_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    fake.motion_finish_sequence = [False] * 100
    adapter = RobotAdapter()
    adapter._api = object()

    result = adapter.wait_until_queue_empty(timeout_s=0.01, poll_interval_s=0.005)

    assert result.ok is False
    assert "Timed out waiting for queue" in (result.error or "")
