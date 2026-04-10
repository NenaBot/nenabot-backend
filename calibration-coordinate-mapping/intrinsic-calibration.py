import cv2
import numpy as np
import os
import glob
import json

# 1. Setup Parameters
CHESSBOARD_SIZE = (8, 6)  # Inner corners for 9x7 grid
SQUARE_SIZE = 34  # Millimeters
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(SCRIPT_DIR, "calibration_images")

# Termination criteria for sub-pixel accuracy
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

# Prepare object points (0,0,0), (34,0,0), (68,0,0) ...
objp = np.zeros((CHESSBOARD_SIZE[0] * CHESSBOARD_SIZE[1], 3), np.float32)
objp[:, :2] = (
    np.mgrid[0 : CHESSBOARD_SIZE[0], 0 : CHESSBOARD_SIZE[1]].T.reshape(-1, 2)
    * SQUARE_SIZE
)

objpoints = []  # 3d point in real world space
imgpoints = []  # 2d points in image plane

# 2. Load Images
images = glob.glob(os.path.join(IMAGE_DIR, "*.png"))
print(f"Found {len(images)} images for calibration.")

valid_images = 0
for fname in images:
    img = cv2.imread(fname)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Find the chess board corners
    ret, corners = cv2.findChessboardCorners(gray, CHESSBOARD_SIZE, None)

    if ret:
        objpoints.append(objp)
        # Refine corner locations to sub-pixel accuracy
        corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        imgpoints.append(corners2)
        valid_images += 1
        print(f"Processed: {os.path.basename(fname)}")

if valid_images < 10:
    print("Error: Not enough valid images found. Check for blur.")
    exit()

# 3. The "Math Lab": Calibrate with Release Object (RO)
print("\nRunning Calibration (Release Object Method)...")
# iFixedPoint is the index of the corner that is 'released' last (usually a corner)
ret, mtx, dist, rvecs, tvecs, new_objpoints = cv2.calibrateCameraRO(
    objpoints,
    imgpoints,
    gray.shape[::-1],
    iFixedPoint=CHESSBOARD_SIZE[0] - 1,
    cameraMatrix=None,
    distCoeffs=None,
    flags=cv2.CALIB_FIX_K3,  # K3 is often unnecessary for standard lenses
)

# 4. Save the Results to JSON
calibration_data = {
    "reprojection_error": ret,
    "camera_matrix": mtx.tolist(),
    "dist_coeff": dist.tolist(),
    "resolution": [gray.shape[1], gray.shape[0]],
}

output_path = os.path.join(SCRIPT_DIR, "camera_params.json")
with open(output_path, "w") as f:
    json.dump(calibration_data, f, indent=4)

print("-" * 30)
print(f"SUCCESS! Reprojection Error: {ret:.4f} pixels")
print(f"Data saved to '{output_path}'")
print("-" * 30)
