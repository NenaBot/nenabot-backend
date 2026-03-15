import cv2
import numpy as np
import json

# 1. Load your calibration results
with open("camera_params.json", "r") as f:
    data = json.load(f)

mtx = np.array(data["camera_matrix"])
dist = np.array(data["dist_coeff"])

# 2. Start the Camera
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# 3. Pre-calculate the 'New Camera Matrix' to handle cropping
# This helps you decide if you want to keep black edges or crop them out
ret, frame = cap.read()
h, w = frame.shape[:2]
new_camera_mtx, roi = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))

print("Showing Undistorted Preview. Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret: break

    # 4. Apply Undistortion
    # This is the core 'Step 4' action
    undistorted_img = cv2.undistort(frame, mtx, dist, None, new_camera_mtx)

    # Optional: Crop the image based on the ROI (Region of Interest)
    x, y, w_roi, h_roi = roi
    undistorted_img = undistorted_img[y:y+h_roi, x:x+w_roi]

    # Display both for comparison
    cv2.imshow("Original (Distorted)", cv2.resize(frame, (960, 540)))
    cv2.imshow("Undistorted Preview", cv2.resize(undistorted_img, (960, 540)))

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()