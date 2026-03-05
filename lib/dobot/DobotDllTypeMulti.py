from ctypes import *
import os
import platform
import time


def enum(**enums):
    return type("Enum", (), enums)


DobotConnect = enum(
    DobotConnect_NoError=0,
    DobotConnect_NotFound=1,
    DobotConnect_Occupied=2,
)

DobotCommunicate = enum(
    DobotCommunicate_NoError=0,
    DobotCommunicate_BufferFull=1,
    DobotCommunicate_Timeout=2,
    DobotCommunicate_InvalidParams=3,
)

PTPMode = enum(
    PTPJUMPXYZMode=0,
    PTPMOVJXYZMode=1,
    PTPMOVLXYZMode=2,
    PTPJUMPANGLEMode=3,
    PTPMOVJANGLEMode=4,
    PTPMOVLANGLEMode=5,
    PTPMOVJANGLEINCMode=6,
    PTPMOVLXYZINCMode=7,
    PTPMOVJXYZINCMode=8,
    PTPJUMPMOVLXYZMode=9,
)


class Pose(Structure):
    _pack_ = 1
    _fields_ = [
        ("x", c_float),
        ("y", c_float),
        ("z", c_float),
        ("r", c_float),
        ("jointAngle", c_float * 4),
    ]


class HOMEParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("x", c_float),
        ("y", c_float),
        ("z", c_float),
        ("r", c_float),
    ]


class HOMECmd(Structure):
    _pack_ = 1
    _fields_ = [("reserved", c_uint32)]


class PTPJointParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("velocity", c_float * 4),
        ("acceleration", c_float * 4),
    ]


class PTPCommonParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("velocityRatio", c_float),
        ("accelerationRatio", c_float),
    ]


class PTPCmd(Structure):
    _pack_ = 1
    _fields_ = [
        ("ptpMode", c_ubyte),
        ("x", c_float),
        ("y", c_float),
        ("z", c_float),
        ("r", c_float),
    ]


class EndEffectorParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("xBias", c_float),
        ("yBias", c_float),
        ("zBias", c_float),
    ]


class JOGJointParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("velocity", c_float * 4),
        ("acceleration", c_float * 4),
    ]


class JOGCoordinateParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("velocity", c_float * 4),
        ("acceleration", c_float * 4),
    ]


class JOGCommonParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("velocityRatio", c_float),
        ("accelerationRatio", c_float),
    ]


class PTPCoordinateParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("xyzVelocity", c_float),
        ("rVelocity", c_float),
        ("xyzAcceleration", c_float),
        ("rAcceleration", c_float),
    ]


class PTPJumpParams(Structure):
    _pack_ = 1
    _fields_ = [
        ("jumpHeight", c_float),
        ("zLimit", c_float),
    ]


_dobot_id = None


def load():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if platform.system() == "Windows":
        dll_path = os.path.join(base_dir, "DobotDll.dll")
        if not os.path.exists(dll_path):
            raise FileNotFoundError("DobotDll.dll not found in lib/dobot/.")
        return CDLL(dll_path, RTLD_GLOBAL)
    if platform.system() == "Darwin":
        dylib_path = os.path.join(base_dir, "libDobotDll.dylib")
        brew_framework_path = "/opt/homebrew/opt/qt@5/lib"
        framework_path = base_dir
        existing_framework_path = os.environ.get("DYLD_FRAMEWORK_PATH", "")
        framework_candidates = [framework_path]
        if platform.machine() == "arm64" and os.path.isdir(brew_framework_path):
            framework_candidates.insert(0, brew_framework_path)
        existing_framework_entries = [p for p in existing_framework_path.split(":") if p]
        updated_framework_entries = [p for p in framework_candidates if p not in existing_framework_entries]
        os.environ["DYLD_FRAMEWORK_PATH"] = ":".join(
            updated_framework_entries + existing_framework_entries
        )
        existing_library_path = os.environ.get("DYLD_LIBRARY_PATH", "")
        if base_dir not in existing_library_path.split(":"):
            os.environ["DYLD_LIBRARY_PATH"] = ":".join(
                [p for p in [base_dir, existing_library_path] if p]
            )
        if not os.path.exists(dylib_path):
            raise FileNotFoundError("libDobotDll.dylib not found in lib/dobot/.")
        return CDLL(dylib_path, RTLD_GLOBAL)
    if platform.system() == "Linux":
        so_path = os.path.join(base_dir, "libDobotDll.so")
        if not os.path.exists(so_path):
            raise FileNotFoundError("libDobotDll.so not found in lib/dobot/.")
        return CDLL(so_path, RTLD_GLOBAL)
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


def _ensure_api(api):
    if not hasattr(api, "_dobot_multi_bound"):
        api.ConnectDobot.argtypes = [c_char_p, c_uint32, c_char_p, c_char_p, POINTER(c_int)]
        api.ConnectDobot.restype = c_int
        api.DisconnectDobot.argtypes = [c_int]
        api.DisconnectDobot.restype = c_int
        api.GetPose.argtypes = [c_int, POINTER(Pose)]
        api.GetPose.restype = c_int
        api.SetHOMEParams.argtypes = [c_int, POINTER(HOMEParams), c_bool, POINTER(c_uint64)]
        api.SetHOMEParams.restype = c_int
        api.SetHOMECmd.argtypes = [c_int, POINTER(HOMECmd), c_bool, POINTER(c_uint64)]
        api.SetHOMECmd.restype = c_int
        api.SetPTPJointParams.argtypes = [c_int, POINTER(PTPJointParams), c_bool, POINTER(c_uint64)]
        api.SetPTPJointParams.restype = c_int
        api.SetPTPCommonParams.argtypes = [c_int, POINTER(PTPCommonParams), c_bool, POINTER(c_uint64)]
        api.SetPTPCommonParams.restype = c_int
        api.SetPTPCmd.argtypes = [c_int, POINTER(PTPCmd), c_bool, POINTER(c_uint64)]
        api.SetPTPCmd.restype = c_int
        api.SetCmdTimeout.argtypes = [c_int, c_uint32]
        api.SetCmdTimeout.restype = c_int
        api.SetEndEffectorParams.argtypes = [c_int, POINTER(EndEffectorParams), c_bool, POINTER(c_uint64)]
        api.SetEndEffectorParams.restype = c_int
        api.SetJOGJointParams.argtypes = [c_int, POINTER(JOGJointParams), c_bool, POINTER(c_uint64)]
        api.SetJOGJointParams.restype = c_int
        api.SetJOGCoordinateParams.argtypes = [c_int, POINTER(JOGCoordinateParams), c_bool, POINTER(c_uint64)]
        api.SetJOGCoordinateParams.restype = c_int
        api.SetJOGCommonParams.argtypes = [c_int, POINTER(JOGCommonParams), c_bool, POINTER(c_uint64)]
        api.SetJOGCommonParams.restype = c_int
        api.SetPTPCoordinateParams.argtypes = [c_int, POINTER(PTPCoordinateParams), c_bool, POINTER(c_uint64)]
        api.SetPTPCoordinateParams.restype = c_int
        api.SetPTPJumpParams.argtypes = [c_int, POINTER(PTPJumpParams), c_bool, POINTER(c_uint64)]
        api.SetPTPJumpParams.restype = c_int
        api.SetQueuedCmdStartExec.argtypes = [c_int]
        api.SetQueuedCmdStartExec.restype = c_int
        api.SetQueuedCmdStopExec.argtypes = [c_int]
        api.SetQueuedCmdStopExec.restype = c_int
        api.SetQueuedCmdClear.argtypes = [c_int]
        api.SetQueuedCmdClear.restype = c_int
        api.GetQueuedCmdCurrentIndex.argtypes = [c_int, POINTER(c_uint64)]
        api.GetQueuedCmdCurrentIndex.restype = c_int
        api._dobot_multi_bound = True


def dSleep(ms):
    time.sleep(ms / 1000)


def ConnectDobot(api, portName, baudrate):
    global _dobot_id
    _ensure_api(api)
    fw_type = create_string_buffer(64)
    version = create_string_buffer(64)
    dobot_id = c_int(0)
    result = api.ConnectDobot(portName.encode("utf-8"), baudrate, fw_type, version, byref(dobot_id))
    if result == DobotConnect.DobotConnect_NoError:
        _dobot_id = dobot_id.value
    return [result, dobot_id.value, fw_type.value.decode("utf-8", errors="ignore"), version.value.decode("utf-8", errors="ignore")]


def DisconnectDobot(api):
    _ensure_api(api)
    if _dobot_id is None:
        return None
    return api.DisconnectDobot(c_int(_dobot_id))


def GetPose(api):
    _ensure_api(api)
    pose = Pose()
    result = api.GetPose(c_int(_dobot_id), byref(pose))
    if result != DobotCommunicate.DobotCommunicate_NoError:
        return [0.0] * 8
    return [
        pose.x,
        pose.y,
        pose.z,
        pose.r,
        pose.jointAngle[0],
        pose.jointAngle[1],
        pose.jointAngle[2],
        pose.jointAngle[3],
    ]


def SetQueuedCmdClear(api):
    _ensure_api(api)
    while True:
        result = api.SetQueuedCmdClear(c_int(_dobot_id))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [result]


def SetCmdTimeout(api, times):
    _ensure_api(api)
    return api.SetCmdTimeout(c_int(_dobot_id), c_uint32(times))


def SetEndEffectorParams(api, xBias, yBias, zBias, isQueued=0):
    _ensure_api(api)
    params = EndEffectorParams(xBias, yBias, zBias)
    queued_index = c_uint64(0)
    while True:
        result = api.SetEndEffectorParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetJOGJointParams(api, velocity, acceleration, isQueued=0):
    _ensure_api(api)
    params = JOGJointParams((c_float * 4)(*velocity), (c_float * 4)(*acceleration))
    queued_index = c_uint64(0)
    while True:
        result = api.SetJOGJointParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetJOGCoordinateParams(api, velocity, acceleration, isQueued=0):
    _ensure_api(api)
    params = JOGCoordinateParams((c_float * 4)(*velocity), (c_float * 4)(*acceleration))
    queued_index = c_uint64(0)
    while True:
        result = api.SetJOGCoordinateParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetJOGCommonParams(api, velocityRatio, accelerationRatio, isQueued=0):
    _ensure_api(api)
    params = JOGCommonParams(velocityRatio, accelerationRatio)
    queued_index = c_uint64(0)
    while True:
        result = api.SetJOGCommonParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetHOMEParams(api, x, y, z, r, isQueued=0):
    _ensure_api(api)
    params = HOMEParams(x, y, z, r)
    queued_index = c_uint64(0)
    while True:
        result = api.SetHOMEParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetHOMECmd(api, temp, isQueued=0):
    _ensure_api(api)
    cmd = HOMECmd(0)
    queued_index = c_uint64(0)
    while True:
        result = api.SetHOMECmd(c_int(_dobot_id), byref(cmd), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetPTPJointParams(api, j1Velocity, j1Acceleration, j2Velocity, j2Acceleration, j3Velocity, j3Acceleration, j4Velocity, j4Acceleration, isQueued=0):
    _ensure_api(api)
    params = PTPJointParams(
        (c_float * 4)(j1Velocity, j2Velocity, j3Velocity, j4Velocity),
        (c_float * 4)(j1Acceleration, j2Acceleration, j3Acceleration, j4Acceleration),
    )
    queued_index = c_uint64(0)
    while True:
        result = api.SetPTPJointParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetPTPCommonParams(api, velocityRatio, accelerationRatio, isQueued=0):
    _ensure_api(api)
    params = PTPCommonParams(velocityRatio, accelerationRatio)
    queued_index = c_uint64(0)
    while True:
        result = api.SetPTPCommonParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetPTPCoordinateParams(api, xyzVelocity, xyzAcceleration, rVelocity, rAcceleration, isQueued=0):
    _ensure_api(api)
    params = PTPCoordinateParams(xyzVelocity, rVelocity, xyzAcceleration, rAcceleration)
    queued_index = c_uint64(0)
    while True:
        result = api.SetPTPCoordinateParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetPTPJumpParams(api, jumpHeight, zLimit, isQueued=0):
    _ensure_api(api)
    params = PTPJumpParams(jumpHeight, zLimit)
    queued_index = c_uint64(0)
    while True:
        result = api.SetPTPJumpParams(c_int(_dobot_id), byref(params), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break
    return [queued_index.value]


def SetPTPCmd(api, ptpMode, x, y, z, rHead, isQueued=0):
    _ensure_api(api)
    cmd = PTPCmd(ptpMode, x, y, z, rHead)
    queued_index = c_uint64(0)
    while True:
        result = api.SetPTPCmd(c_int(_dobot_id), byref(cmd), c_bool(isQueued), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(2)
            continue
        break
    return [queued_index.value]


def SetQueuedCmdStartExec(api):
    _ensure_api(api)
    while True:
        result = api.SetQueuedCmdStartExec(c_int(_dobot_id))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break


def SetQueuedCmdStopExec(api):
    _ensure_api(api)
    while True:
        result = api.SetQueuedCmdStopExec(c_int(_dobot_id))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(5)
            continue
        break


def GetQueuedCmdCurrentIndex(api):
    _ensure_api(api)
    queued_index = c_uint64(0)
    while True:
        result = api.GetQueuedCmdCurrentIndex(c_int(_dobot_id), byref(queued_index))
        if result != DobotCommunicate.DobotCommunicate_NoError:
            dSleep(2)
            continue
        break
    return [queued_index.value]
