import argparse
import importlib
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest


def import_main_with_fake_cv2(monkeypatch, fake_cv2):
    """Import (or reload) main.py after injecting a fake cv2 module."""
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def make_fake_cv2_for_happy_path():
    """
    Build a fake cv2 module that simulates:
    - camera open + one successful frame read
    - ArUco marker detection that yields a usable pixels_per_mm
    - one contour that passes filters and yields a measurement
    - user presses 'q' to exit after first frame
    """
    cv2 = ModuleType("cv2")

    # --- constants used by main.py ---
    cv2.CAP_DSHOW = 700
    cv2.CAP_PROP_FRAME_WIDTH = 3
    cv2.CAP_PROP_FRAME_HEIGHT = 4
    cv2.COLOR_BGR2GRAY = 6
    cv2.RETR_EXTERNAL = 0
    cv2.CHAIN_APPROX_SIMPLE = 0
    cv2.FONT_HERSHEY_SIMPLEX = 0

    # --- call recording ---
    calls = {
        "VideoCapture_init": None,
        "cap_set": [],
        "cap_read": 0,
        "cap_release": 0,
        "destroyAllWindows": 0,
        "imshow": 0,
        "waitKey": 0,
        "putText": [],
        "drawContours": 0,
        "polylines": 0,
        "aruco_drawDetectedMarkers": 0,
    }

    # --- fake camera ---
    class FakeCapture:
        def __init__(self, index, backend):
            calls["VideoCapture_init"] = (index, backend)
            self._opened = True

        def set(self, prop, value):
            calls["cap_set"].append((prop, value))
            return True

        def isOpened(self):
            return self._opened

        def read(self):
            # First read succeeds, second fails (loop would also exit via waitKey anyway).
            calls["cap_read"] += 1
            if calls["cap_read"] == 1:
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                return True, frame
            return False, None

        def release(self):
            calls["cap_release"] += 1

    cv2.VideoCapture = FakeCapture

    # --- image processing stubs ---
    def cvtColor(frame, code):
        assert code == cv2.COLOR_BGR2GRAY
        return np.zeros((720, 1280), dtype=np.uint8)

    def GaussianBlur(gray, ksize, sigma):
        return gray

    def Canny(img, t1, t2):
        return np.zeros_like(img)

    def dilate(img, kernel, iterations=1):
        return img

    cv2.cvtColor = cvtColor
    cv2.GaussianBlur = GaussianBlur
    cv2.Canny = Canny
    cv2.dilate = dilate

    # --- contours pipeline ---
    FAKE_CONTOUR = object()

    def findContours(edges, mode, method):
        # Return one external contour
        return [FAKE_CONTOUR], None

    def contourArea(contour):
        assert contour is FAKE_CONTOUR
        return 20000  # passes area filter (8000..150000)

    def arcLength(contour, closed):
        return 400.0

    def approxPolyDP(contour, eps, closed):
        # 4 vertices -> passes "rectangle-ish" filter (4..8)
        return [0, 1, 2, 3]

    def minAreaRect(contour):
        # center, (width_px, height_px), angle
        return ((320.0, 240.0), (96.0, 48.0), 0.0)

    def boxPoints(rect):
        # Return 4 points; values don't matter beyond being array-like.
        return np.array([[0, 0], [96, 0], [96, 48], [0, 48]], dtype=np.float32)

    cv2.findContours = findContours
    cv2.contourArea = contourArea
    cv2.arcLength = arcLength
    cv2.approxPolyDP = approxPolyDP
    cv2.minAreaRect = minAreaRect
    cv2.boxPoints = boxPoints

    # --- drawing + UI stubs ---
    def polylines(img, pts, isClosed, color, thickness):
        calls["polylines"] += 1

    def drawContours(img, contours, idx, color, thickness):
        calls["drawContours"] += 1

    def mean(gray, mask=None):
        # Low intensity -> passes "dark region" filter (<=150)
        return (100.0, 0.0, 0.0, 0.0)

    def putText(img, text, org, font, fontScale, color, thickness):
        calls["putText"].append(text)

    def imshow(name, frame):
        calls["imshow"] += 1

    def waitKey(delay):
        calls["waitKey"] += 1
        return ord("q")  # exit loop immediately

    def destroyAllWindows():
        calls["destroyAllWindows"] += 1

    cv2.polylines = polylines
    cv2.drawContours = drawContours
    cv2.mean = mean
    cv2.putText = putText
    cv2.imshow = imshow
    cv2.waitKey = waitKey
    cv2.destroyAllWindows = destroyAllWindows

    # --- fake aruco submodule ---
    aruco = SimpleNamespace()
    aruco.DICT_4X4_50 = 123

    def getPredefinedDictionary(dict_id):
        assert dict_id == aruco.DICT_4X4_50
        return {"dict_id": dict_id}

    class DetectorParameters:
        pass

    class ArucoDetector:
        def __init__(self, aruco_dict, detector_params):
            self.aruco_dict = aruco_dict

        def detectMarkers(self, gray):
            # Provide corners so that side length is 48 px.
            # marker_corners[0] - marker_corners[1] norm = 48
            marker = np.array(
                [[[0.0, 0.0], [48.0, 0.0], [48.0, 48.0], [0.0, 48.0]]],
                dtype=np.float32,
            )
            corners = [marker]
            ids = np.array([[0]], dtype=np.int32)
            return corners, ids, None

    def drawDetectedMarkers(frame, corners, ids):
        calls["aruco_drawDetectedMarkers"] += 1

    aruco.getPredefinedDictionary = getPredefinedDictionary
    aruco.DetectorParameters = DetectorParameters
    aruco.ArucoDetector = ArucoDetector
    aruco.drawDetectedMarkers = drawDetectedMarkers

    cv2.aruco = aruco

    # Expose calls so tests can assert behavior
    cv2._calls = calls
    return cv2


def make_fake_cv2_camera_not_open():
    """Fake cv2 where VideoCapture.isOpened() returns False."""
    cv2 = ModuleType("cv2")

    cv2.CAP_DSHOW = 700
    cv2.CAP_PROP_FRAME_WIDTH = 3
    cv2.CAP_PROP_FRAME_HEIGHT = 4
    cv2.COLOR_BGR2GRAY = 6

    aruco = SimpleNamespace()
    aruco.DICT_4X4_50 = 123

    def getPredefinedDictionary(dict_id):
        return {"dict_id": dict_id}

    class DetectorParameters:
        pass

    class ArucoDetector:
        def __init__(self, aruco_dict, detector_params):
            pass

    aruco.getPredefinedDictionary = getPredefinedDictionary
    aruco.DetectorParameters = DetectorParameters
    aruco.ArucoDetector = ArucoDetector
    cv2.aruco = aruco

    class FakeCapture:
        def __init__(self, index, backend):
            pass

        def set(self, prop, value):
            return True

        def isOpened(self):
            return False

    cv2.VideoCapture = FakeCapture
    return cv2


def test_parse_args_defaults(monkeypatch):
    fake_cv2 = make_fake_cv2_for_happy_path()
    main = import_main_with_fake_cv2(monkeypatch, fake_cv2)

    monkeypatch.setattr(sys, "argv", ["prog"])
    args = main.parse_args()

    assert args.marker_size == 48.0
    assert args.camera == 0


def test_parse_args_custom(monkeypatch):
    fake_cv2 = make_fake_cv2_for_happy_path()
    main = import_main_with_fake_cv2(monkeypatch, fake_cv2)

    monkeypatch.setattr(sys, "argv", ["prog", "--marker-size", "40.5", "--camera", "2"])
    args = main.parse_args()

    assert args.marker_size == 40.5
    assert args.camera == 2


def test_main_raises_if_camera_cannot_open(monkeypatch):
    fake_cv2 = make_fake_cv2_camera_not_open()
    main = import_main_with_fake_cv2(monkeypatch, fake_cv2)

    fake_args = argparse.Namespace(marker_size=48.0, camera=0)
    monkeypatch.setattr(main, "parse_args", lambda: fake_args)

    with pytest.raises(RuntimeError, match="Unable to open camera"):
        main.main()


def test_main_happy_path_marker_detected_and_measurement_rendered(monkeypatch):
    fake_cv2 = make_fake_cv2_for_happy_path()
    main = import_main_with_fake_cv2(monkeypatch, fake_cv2)

    # marker_size=48mm and marker side length=48px -> pixels_per_mm = 1.0
    fake_args = argparse.Namespace(marker_size=48.0, camera=0)
    monkeypatch.setattr(main, "parse_args", lambda: fake_args)

    main.main()

    calls = fake_cv2._calls

    # Camera opened with expected backend and index
    assert calls["VideoCapture_init"] == (0, fake_cv2.CAP_DSHOW)

    # Resolution set
    assert (fake_cv2.CAP_PROP_FRAME_WIDTH, 1280) in calls["cap_set"]
    assert (fake_cv2.CAP_PROP_FRAME_HEIGHT, 720) in calls["cap_set"]

    # Marker drawing path executed
    assert calls["aruco_drawDetectedMarkers"] == 1
    assert calls["polylines"] == 1

    # Measurement + status text should be rendered
    # From minAreaRect (96x48 px) with pixels_per_mm=1 -> "96.0x48.0 mm"
    assert any("96.0x48.0 mm" == t for t in calls["putText"])
    assert any("Marker detected" == t for t in calls["putText"])
    assert any("Press Q to quit" == t for t in calls["putText"])

    # Cleanup
    assert calls["cap_release"] == 1
    assert calls["destroyAllWindows"] == 1
