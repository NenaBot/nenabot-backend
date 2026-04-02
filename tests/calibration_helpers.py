from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


def sample_intrinsics() -> dict:
    return {
        "camera_matrix": [
            [1000.0, 0.0, 640.0],
            [0.0, 1000.0, 360.0],
            [0.0, 0.0, 1.0],
        ],
        "dist_coeff": [[0.0, 0.0, 0.0, 0.0, 0.0]],
        "resolution": [1280, 720],
        "checkerboard": {
            "inner_corners": [8, 6],
            "square_size_mm": 34.0,
        },
    }


def sample_correspondences() -> (
    tuple[list[tuple[float, float]], list[tuple[float, float, float]]]
):
    image_points = [
        (100.0, 100.0),
        (200.0, 100.0),
        (200.0, 200.0),
        (100.0, 200.0),
    ]
    robot_points = [
        (200.0, 100.0, -50.0),
        (300.0, 100.0, -50.0),
        (300.0, 200.0, -50.0),
        (200.0, 200.0, -50.0),
    ]
    return image_points, robot_points


def write_intrinsics(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample_intrinsics(), indent=4))
    return path


def write_mapping(
    path: Path,
    intrinsics_path: Path,
    calibrated_at: str = "2026-04-02T10:00:00+00:00",
) -> Path:
    intrinsics = sample_intrinsics()
    image_points, robot_points = sample_correspondences()

    camera_matrix = np.array(intrinsics["camera_matrix"], dtype=np.float64)
    dist_coeff = np.array(intrinsics["dist_coeff"], dtype=np.float64)
    success, rvec, tvec = cv2.solvePnP(
        np.array(robot_points, dtype=np.float64),
        np.array(image_points, dtype=np.float64).reshape(-1, 1, 2),
        camera_matrix,
        dist_coeff,
    )
    if not success:
        raise RuntimeError("solvePnP failed in test fixture")

    mapping = {
        "calibrated_at": calibrated_at,
        "intrinsics_path": str(intrinsics_path),
        "resolution": intrinsics["resolution"],
        "checkerboard": {
            "inner_corners": [8, 6],
            "square_size_mm": 34.0,
            "fixed_points": [[1, 0], [1, 6], [5, 7], [5, 0]],
        },
        "image_points": [
            {
                "row": row,
                "col": col,
                "pixelX": point[0],
                "pixelY": point[1],
            }
            for (row, col), point in zip(
                ((1, 0), (1, 6), (5, 7), (5, 0)),
                image_points,
            )
        ],
        "robot_points": [
            {
                "row": row,
                "col": col,
                "robotX": point[0],
                "robotY": point[1],
                "robotZ": point[2],
            }
            for (row, col), point in zip(
                ((1, 0), (1, 6), (5, 7), (5, 0)),
                robot_points,
            )
        ],
        "start_pose": {"x": 10.0, "y": 20.0, "z": 30.0, "r": 40.0},
        "rvec": rvec.tolist(),
        "tvec": tvec.tolist(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=4))
    return path
