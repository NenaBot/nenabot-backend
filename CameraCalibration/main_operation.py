import cv2
import numpy as np
import json
import DobotDllType as dType

# 1. LOAD CONFIGURATIONS
with open("camera_params.json", "r") as f:
    cam_data = json.load(f)
with open("robot_mapping.json", "r") as f:
    map_data = json.load(f)

MTX = np.array(cam_data["camera_matrix"])
DIST = np.array(cam_data["dist_coeff"])
RVEC = np.array(map_data["rvec"])
TVEC = np.array(map_data["tvec"])
Z_BASE = map_data["robot_z_baseline"]

# 2. INITIALIZE DOBOT
api = dType.load()
dType.ConnectDobot(api, "", 115200)
dType.SetQueuedCmdClear(api)

# 3. COORDINATE TRANSFORMATION LOGIC
def pixel_to_robot(u, v):
    """
    Converts (u, v) pixel to (X, Y) Robot coordinates 
    using the PnP results.
    """
    # Standard transformation math for a plane
    R, _ = cv2.Rodrigues(RVEC)
    invR = np.linalg.inv(R)
    
    uv_homo = np.array([[u], [v], [1.0]])
    invMTX = np.linalg.inv(MTX)
    
    left = invR @ invMTX @ uv_homo
    right = invR @ TVEC
    
    # Solve for scale 's' to find the intersection with the Z plane
    s = (0 + right[2,0]) / left[2,0]
    robot_coords = invR @ (s * invMTX @ uv_homo - TVEC)
    
    return robot_coords[0,0], robot_coords[1,0]

# 4. MOUSE CALLBACK FOR UI
def on_click(event, u, v, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        robot_x, robot_y = pixel_to_robot(u, v)
        print(f"Clicked Pixel: ({u}, {v}) -> Robot Target: X={robot_x:.2f}, Y={robot_y:.2f}")
        
        # Execute movement (Requirement IX: Fully Autonomous)
        # We move to the calculated X, Y and our calibrated Z baseline
        dType.SetPTPCmd(api, dType.PTPMode.PTPMOVLXYZMode, robot_x, robot_y, Z_BASE, 0)

# 5. MAIN LOOP
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cv2.namedWindow("Dobot Vision System")
cv2.setMouseCallback("Dobot Vision System", on_click)

print("System Ready. Click anywhere on the video to move the Dobot.")

while True:
    ret, frame = cap.read()
    if not ret: break
    
    # Undistort frame (Requirement I: Graphical Preview)
    undistorted = cv2.undistort(frame, MTX, DIST)
    
    display = cv2.resize(undistorted, (1280, 720))
    cv2.imshow("Dobot Vision System", display)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

dType.DisconnectDobot(api)
cap.release()
cv2.destroyAllWindows()