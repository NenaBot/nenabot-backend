import argparse
import math

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure object size using an ArUco marker scale"
    )
    parser.add_argument(
        "--marker-size",
        type=float,
        default=48.0,
        help="ArUco marker side length in millimeters",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Camera index (default: 0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector_params = cv2.aruco.DetectorParameters()
    detector = cv2.aruco.ArucoDetector(aruco_dict, detector_params)

    # Open camera
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    
    # Set high resolution for better accuracy
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)


    if not cap.isOpened():
        raise RuntimeError("Unable to open camera")

    pixels_per_mm = None

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect ArUco markers
        corners, ids, _ = detector.detectMarkers(gray)
        
        if ids is not None and len(corners) > 0:
            # Draw detected markers
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
            
            # Calculate scale from first marker
            marker_corners = corners[0][0]
            side_length = np.linalg.norm(marker_corners[0] - marker_corners[1])
            pixels_per_mm = side_length / args.marker_size
            
            # Draw marker outline
            pts = marker_corners.astype(int)
            cv2.polylines(frame, [pts], True, (0, 255, 0), 2)

        # Simple edge detection for battery outlines
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blurred, 50, 150)
        
        # Light morphology
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Filter and measure contours
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 8000 or area > 150000:
                continue
            
            # Approximate polygon
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            
            # Look for 4-sided shapes (rectangles)
            if len(approx) < 4 or len(approx) > 8:
                continue
                
            # Get rotated bounding box
            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect)
            box = box.astype(int)
            
            # Filter by aspect ratio
            width, height = rect[1]
            if width == 0 or height == 0:
                continue
            aspect_ratio = max(width, height) / min(width, height)
            if aspect_ratio < 1.05 or aspect_ratio > 3.5:
                continue
            
            # Check for dark regions (battery sticker) inside contour
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(mask, [contour], -1, 255, -1)
            mean_intensity = cv2.mean(gray, mask=mask)[0]
            if mean_intensity > 150:
                continue
            
            if pixels_per_mm is not None:
                # Calculate dimensions
                width = rect[1][0] / pixels_per_mm
                height = rect[1][1] / pixels_per_mm
                
                # Draw box
                cv2.drawContours(frame, [box], 0, (0, 255, 255), 2)
                
                # Display measurements
                center = tuple(map(int, rect[0]))
                cv2.putText(
                    frame,
                    f"{width:.1f}x{height:.1f} mm",
                    (center[0] - 50, center[1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    2,
                )
            else:
                cv2.drawContours(frame, [box], 0, (0, 0, 255), 2)

        # Status text
        status = "Marker detected" if pixels_per_mm else "No marker - place marker in view"
        color = (0, 255, 0) if pixels_per_mm else (0, 0, 255)
        cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        cv2.putText(frame, "Press Q to quit", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow("Object Measurement", frame)

        if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
