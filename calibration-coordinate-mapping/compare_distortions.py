# This code captures video from the camera, applies the undistortion transformation using the previously calculated camera parameters, and displays a side-by-side preview of the original (distorted) and undistorted images. It also allows you to save both versions of the image when you press the 's' key.


import cv2
import numpy as np
import json
import os

# 1. Load Calibration
if not os.path.exists("camera_params.json"):
    print("Error: camera_params.json not found!")
    exit()

with open("camera_params.json", "r") as f:
    data = json.load(f)
mtx = np.array(data["camera_matrix"])
dist = np.array(data["dist_coeff"])

# 2. Start Camera
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# Get the optimal matrix to keep the edges
ret, frame = cap.read()
h, w = frame.shape[:2]
new_camera_mtx, _ = cv2.getOptimalNewCameraMatrix(mtx, dist, (w, h), 1, (w, h))

print("--- Image Capture Mode ---")
print("Press 's' to Save the current frame (Distorted and Undistorted).")
print("Press 'q' to Quit.")

# Create a window for the live preview
cv2.namedWindow("Preview", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Preview", 1280, 720)

save_count = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 3. Create the mathematical flattened version
    undistorted = cv2.undistort(frame, mtx, dist, None, new_camera_mtx)

    # 4. Create a side-by-side preview for your screen
    # (We resize these just so they fit on your monitor, the saved files will be full 1080p)
    display_raw = cv2.resize(frame, (640, 360))
    display_flat = cv2.resize(undistorted, (640, 360))
    preview = cv2.hconcat([display_raw, display_flat])

    cv2.putText(
        preview,
        "RAW (Press 's' to save)",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 0, 255),
        2,
    )
    cv2.putText(
        preview, "UNDISTORTED", (660, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
    )

    cv2.imshow("Preview", preview)

    key = cv2.waitKey(1) & 0xFF

    # 5. Save the images when 's' is pressed
    if key == ord("s"):
        save_count += 1
        raw_filename = f"comparison_{save_count:02d}_RAW.png"
        flat_filename = f"comparison_{save_count:02d}_FLAT.png"

        # Saving the original 'frame' and 'undistorted' variables which are the full 1080p versions, not the resized previews.
        cv2.imwrite(raw_filename, frame)
        cv2.imwrite(flat_filename, undistorted)

        print(f"[{save_count}] Saved successfully: {raw_filename} & {flat_filename}")

    elif key == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
print("Capture session ended.")
