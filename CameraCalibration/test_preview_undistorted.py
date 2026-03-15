import cv2
import numpy as np
import json
import sys

# 1. Load your calibration results (Requirement 8: Machine-readable data)
try:
    with open("camera_params.json", "r") as f:
        data = json.load(f)
    print("Calibration data loaded successfully.")
except FileNotFoundError:
    print("ERROR: camera_params.json not found. Run the calibration script first!")
    sys.exit(1)

mtx = np.array(data["camera_matrix"])
dist = np.array(data["dist_coeff"])

# 2. Start the Camera (Using DirectShow for Windows stability)
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# 3. Setup Optimal Matrix to handle the 'Edges'
# We grab one frame to get the correct dimensions
ret, frame = cap.read()
if not ret:
    print("ERROR: Could not read from camera.")
    sys.exit(1)

h, w = frame.shape[:2]
# This function calculates how to scale the image after it is 'flattened'
new_camera_mtx, roi = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))

print("\n--- Undistortion Preview Active ---")
print("Look at the straight lines of your chessboard.")
print("Press 'q' to Quit.")

while True:
    ret, frame = cap.read()
    if not ret: break

    # 4. Core Undistortion Action (Step 4 of Systematic View)
    # This transforms the 'warped' pixels back to their true positions
    undistorted_img = cv2.undistort(frame, mtx, dist, None, new_camera_mtx)

    # Optional: Draw a grid overlay to help you see the 'flatness'
    # This helps verify if the image is ready for 'Exact Coordinates'
    grid_color = (0, 255, 255) # Yellow
    for i in range(0, w, 100):
        cv2.line(undistorted_img, (i, 0), (i, h), grid_color, 1)
    for j in range(0, h, 100):
        cv2.line(undistorted_img, (0, j), (w, j), grid_color, 1)

    # 5. Display both for comparison
    # We resize them just for the display so they fit on your monitor
    cv2.imshow("Original Distorted Feed", cv2.resize(frame, (960, 540)))
    cv2.imshow("RECTIFIED (Flat) Preview", cv2.resize(undistorted_img, (960, 540)))

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()