from __future__ import annotations

import sys
import types

import pytest

from app.adapters.robot import RobotAdapter, _get_dobot_dll_type


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


def test_get_dobot_dll_type_windows_uses_normal_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    dobot_module = _get_dobot_dll_type()

    assert dobot_module.__name__.endswith("DobotDllType")


def test_get_dobot_dll_type_non_windows_uses_multi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    dobot_module = _get_dobot_dll_type()

    assert dobot_module.__name__.endswith("Multi")


def test_connect_failure_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    fake.connect_ret = 2
    adapter = RobotAdapter()

    result = adapter.connect("COM7")

    assert result.ok is False
    assert "COM7->2" in (result.error or "")


def test_connect_tries_windows_extended_com_notation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_dobot(monkeypatch)
    returns = [2, 0]

    def _connect(api, port, baud):
        fake.calls.append(("ConnectDobot", (api, port, baud)))
        return (returns.pop(0),)

    fake.ConnectDobot = _connect
    monkeypatch.setattr(sys, "platform", "win32")

    adapter = RobotAdapter()
    result = adapter.connect("COM11")

    assert result.ok is True
    connect_calls = [
        call for call in fake.calls if call[0] == "ConnectDobot"
    ]
    assert [args[1] for _, args in connect_calls] == ["COM11", "\\\\.\\COM11"]


def test_connect_first_available_handles_dll_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenDobotDllType:
        @staticmethod
        def load():
            raise FileNotFoundError("DobotDll.dll not found in lib/dobot/.")

    monkeypatch.setattr(
        "app.adapters.robot._get_dobot_dll_type", lambda: _BrokenDobotDllType
    )
    adapter = RobotAdapter()

    result = adapter.connect_first_available()

    assert result.ok is False
    assert "Dobot DLL load failed" in (result.error or "")


def test_move_to_coordinates_requires_connection() -> None:
    adapter = RobotAdapter()

    result = adapter.move_to_coordinates((1, 2, 3, 4))

    assert result.ok is False
    assert result.error == "No Dobot connection"


def test_move_to_coordinates_wait_and_nonwait(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_dobot(monkeypatch)
    adapter = RobotAdapter()
    adapter._api = object()

    wait_result = adapter.move_to_coordinates((10, 20, 30, 40), wait=True)
    queue_result = adapter.move_to_coordinates((11, 21, 31, 41), wait=False)

    assert wait_result.ok is True
    assert queue_result.ok is True
    assert [name for name, _ in fake.calls] == ["SetPTPCmdEx", "SetPTPCmd"]


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


def test_windows_port_scan_reads_from_first_registry_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _KeyHandle:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeWinReg:
        HKEY_LOCAL_MACHINE = object()

        def OpenKey(self, root, path):
            assert root is self.HKEY_LOCAL_MACHINE
            if path == r"HARDWARE\DEVICEMAP\SERIALCOMM":
                return _KeyHandle(
                    [
                        ("\\Device\\Serial0", "COM7", 1),
                        ("\\Device\\Serial1", "COM3", 1),
                        ("\\Device\\Lpt", "LPT1", 1),
                    ]
                )
            if path == r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Ports":
                return _KeyHandle([])
            raise OSError("missing key")

        def EnumValue(self, key, index):
            try:
                return key.values[index]
            except IndexError as exc:
                raise OSError("done") from exc

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinReg())

    adapter = RobotAdapter()
    assert adapter._list_candidate_ports() == ["COM3", "COM7"]


def test_windows_port_scan_falls_back_to_ports_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _KeyHandle:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeWinReg:
        HKEY_LOCAL_MACHINE = object()

        def OpenKey(self, root, path):
            assert root is self.HKEY_LOCAL_MACHINE
            if path == r"HARDWARE\DEVICEMAP\SERIALCOMM":
                raise OSError("missing")
            if path == r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Ports":
                return _KeyHandle(
                    [
                        ("COM11:", "", 1),
                        ("COM2:", "", 1),
                        ("NotCom", "COM5", 1),
                    ]
                )
            raise OSError("missing key")

        def EnumValue(self, key, index):
            try:
                return key.values[index]
            except IndexError as exc:
                raise OSError("done") from exc

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinReg())

    adapter = RobotAdapter()
    assert adapter._list_candidate_ports() == ["COM2", "COM5", "COM11"]
