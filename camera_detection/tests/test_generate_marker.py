import argparse
import numpy as np
import pytest

from camera_detection import generate_marker


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog"])
    args = generate_marker.parse_args()

    assert args.dict == "DICT_4X4_50"
    assert args.id == 0
    assert args.size == 800
    assert args.output == "marker_4x4_50_id0.png"


def test_parse_args_custom(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--dict",
            "DICT_6X6_250",
            "--id",
            "42",
            "--size",
            "256",
            "--output",
            "out/custom.png",
        ],
    )
    args = generate_marker.parse_args()

    assert args.dict == "DICT_6X6_250"
    assert args.id == 42
    assert args.size == 256
    assert args.output == "out/custom.png"


def test_main_unknown_dict_raises(monkeypatch, tmp_path):
    # parse_args() returns a dictionary name that cv2.aruco does not recognize
    fake_args = argparse.Namespace(
        dict="DICT_DOES_NOT_EXIST",
        id=0,
        size=100,
        output=str(tmp_path / "marker.png"),
    )
    monkeypatch.setattr(generate_marker, "parse_args", lambda: fake_args)

    class FakeAruco:
        # Does NOT contain the attribute DICT_DOES_NOT_EXIST
        pass

    class FakeCv2:
        aruco = FakeAruco()

    monkeypatch.setattr(generate_marker, "cv2", FakeCv2)

    with pytest.raises(ValueError, match="Unknown ArUco dictionary"):
        generate_marker.main()


def test_main_generates_and_writes_image(monkeypatch, tmp_path):
    out_file = tmp_path / "nested" / "dir" / "marker.png"

    fake_args = argparse.Namespace(
        dict="DICT_4X4_50",
        id=7,
        size=64,
        output=str(out_file),
    )
    monkeypatch.setattr(generate_marker, "parse_args", lambda: fake_args)

    calls = {"get_dict": None, "gen": None, "imwrite": None}

    class FakeAruco:
        DICT_4X4_50 = 123

        @staticmethod
        def getPredefinedDictionary(dict_id):
            calls["get_dict"] = dict_id
            return {"dict_id": dict_id}

        @staticmethod
        def generateImageMarker(aruco_dict, marker_id, size):
            calls["gen"] = (aruco_dict, marker_id, size)
            # Return an "image" as a numpy array, as OpenCV typically does
            return np.zeros((size, size), dtype=np.uint8)

    class FakeCv2:
        aruco = FakeAruco()

        @staticmethod
        def imwrite(path, img):
            calls["imwrite"] = (path, img.copy())
            return True

    monkeypatch.setattr(generate_marker, "cv2", FakeCv2)

    # Execute
    generate_marker.main()

    # The output directory was created
    assert out_file.parent.exists()
    assert out_file.parent.is_dir()

    # getPredefinedDictionary was called with the correct ID
    assert calls["get_dict"] == FakeAruco.DICT_4X4_50

    # generateImageMarker was called with the expected arguments
    aruco_dict, marker_id, size = calls["gen"]
    assert aruco_dict == {"dict_id": FakeAruco.DICT_4X4_50}
    assert marker_id == 7
    assert size == 64

    # imwrite was called with the correct path and "image"
    path, img = calls["imwrite"]
    assert path == str(out_file)
    assert isinstance(img, np.ndarray)
    assert img.shape == (64, 64)
