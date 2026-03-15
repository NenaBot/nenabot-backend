import cv2
import numpy as np
import json

# 1. Load Intrinsic Data (from Step 3)
with open("camera_params.json", "r") as f:
    calib = json.load(f)
mtx = np.array(calib["camera_matrix"])
dist = np.array(calib["dist_coeff"])

# 2. Your Collected Data (The Robot Touch)
# Format: [Row, Col] -> [X, Y, Z]
captured_data = [
    {"idx": [1, 0], "robot": [317.29, 108.47, -49.27]},
    {"idx": [1, 6], "robot": [315.84, -101.82, -49.65]},
    {"idx": [5, 7], "robot": [179.61, -139.72, -50.71]},
    {"idx": [5, 0], "robot": [182.96, 113.75, -48.67]}
]

# 3. Setup the Math
# We need the pixel coordinates (u, v) of these corners from a fresh rectified image.
# For this script, we'll use a live snapshot to find them.
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

print("Detecting pixels for the 4 corners...")
# Warm up the camera — discard initial black frames
for _ in range(30):
    cap.read()

ret, frame = cap.read()
if not ret or frame is None:
    print("Error: Could not read from camera!")
    exit()
cv2.imwrite("debug_frame.jpg", frame)  # inspect what the camera actually sees

gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
found, corners = cv2.findChessboardCorners(gray, (8, 6), None)

if found:
    # 1. Draw the rainbow line and dots on the picture
    cv2.drawChessboardCorners(frame, (8, 6), corners, found)
    
    # 2. Pop up a window to show you
    cv2.imshow("Corner Check - Press ANY KEY to close", cv2.resize(frame, (960, 540)))
    cv2.waitKey(0) # Pauses the code until you press a key on your keyboard
    cv2.destroyAllWindows()

if not found:
    print("Error: Board not detected. Ensure the board is still taped down!")
    exit()

# Extract the specific (u, v) pixels for your 4 chosen points
# (In an 8x6 inner corner grid, index = row * 8 + col)
img_pts = []
obj_pts = [] # These will be the Robot (X, Y, Z)

for p in captured_data:
    row, col = p["idx"]
    flat_idx = row * 8 + col
    img_pts.append(corners[flat_idx])
    obj_pts.append(p["robot"])

img_pts = np.array(img_pts, dtype=np.float32)
obj_pts = np.array(obj_pts, dtype=np.float32)

# 4. Solve for Extrinsics (Step 5)
# This calculates how the camera is positioned relative to the Robot Base
success, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, mtx, dist)

if success:
    # Save the 'Transformation' result
    mapping_result = {
        "rvec": rvec.tolist(),
        "tvec": tvec.tolist(),
        "robot_z_baseline": -42.0 # Average of your touched Z points
    }
    with open("robot_mapping.json", "w") as f:
        json.dump(mapping_result, f, indent=4)
    print("SUCCESS: Transformation Matrix generated and saved.")