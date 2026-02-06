import argparse
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a printable ArUco marker image")
    parser.add_argument(
        "--dict",
        default="DICT_4X4_50",
        help="ArUco dictionary name (e.g., DICT_4X4_50)",
    )
    parser.add_argument("--id", type=int, default=0, help="Marker id")
    parser.add_argument(
        "--size",
        type=int,
        default=800,
        help="Marker image size in pixels (square)",
    )
    parser.add_argument(
        "--output",
        default="marker_4x4_50_id0.png",
        help="Output image filename",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not hasattr(cv2.aruco, args.dict):
        raise ValueError(f"Unknown ArUco dictionary: {args.dict}")

    aruco_dict_id = getattr(cv2.aruco, args.dict)
    aruco_dict = cv2.aruco.getPredefinedDictionary(aruco_dict_id)

    marker = cv2.aruco.generateImageMarker(aruco_dict, args.id, args.size)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), marker)


if __name__ == "__main__":
    main()
