# This code is used to test the accuracy of the camera calibration by allowing you to click on the video feed and see where the Dobot arm moves in response. We can adjust the X and Y offsets in the code to fine-tune the accuracy based on your specific setup and the thickness of any objects we are trying to interact with. The code also includes safety checks to prevent the arm from moving outside of its physical limits, and it forces a safe Z height to avoid crashing into the table.


import cv2
import numpy as np
import json
import DobotDllType as dType

# INITIALIZE DOBOT
import time

api = dType.load()
dType.ConnectDobot(api, "COM5", 115200)
dType.SetQueuedCmdClear(api)
dType.SetPTPCommonParams(api, 100, 100)


# --- OFFSETS for the arm ---
X_OFFSET = -2.0  # Adjust if it misses consistently in X (e.g., 2.5)
Y_OFFSET = -2.0  # Adjust if it misses consistently in Y (e.g., -1.2)

# --- THE AUTOMATIC HOMING SEQUENCE ---
print("Homing Dobot... Please stand clear!")
dType.SetHOMECmd(api, temp=0, isQueued=1)

# The homing sequence takes about 15 seconds to physically complete.
# We pause the Python script here so the user can't click prematurely.
time.sleep(15) 
print("Homing Complete! System Ready.")


# 1. LOAD DATA
with open("camera_params.json", "r") as f:
    calib = json.load(f)
with open("robot_mapping.json", "r") as f:
    mapping = json.load(f)

mtx = np.array(calib["camera_matrix"])
dist = np.array(calib["dist_coeff"])
rvec = np.array(mapping["rvec"])
tvec = np.array(mapping["tvec"])

# 2. CONFIGURATION
# Set this to the thickness of the battery you are sampling (in mm)
# If you are touching the board itself, set to 0
CURRENT_THICKNESS = 0.0 

def pixel_to_robot_3d(u, v, thickness_offset):
    # Convert rvec to rotation matrix
    R, _ = cv2.Rodrigues(rvec)
    R_inv = np.linalg.inv(R)
    mtx_inv = np.linalg.inv(mtx)

    # Transform pixel to a ray in Robot World space
    uv_point = np.array([[u], [v], [1.0]])
    ray_cam = mtx_inv.dot(uv_point)
    ray_world = R_inv.dot(ray_cam)
    cam_pos_world = -R_inv.dot(tvec)

    # We want to find the intersection with a plane parallel to the board
    # but raised by 'thickness_offset'. 
    # In Board Space, the board is Z=0. In Robot Space, it's slanted.
    # The simplest way: Find intersection with the plane where the board lies.
    
    # Calculate scale 's' to hit the plane
    # Normal of the board in robot space is the 3rd column of R_inv
    normal_world = R_inv[:, 2]
    
    # Intersection formula for a point on a plane
    # We use one of your calibration points as a reference for the plane height
    
    p0 = np.array([317.29, 108.47, -49.27 + thickness_offset])
    
    denom = np.dot(ray_world.flatten(), normal_world)
    if abs(denom) < 1e-6:
        return None

    s = np.dot((p0 - cam_pos_world.flatten()), normal_world) / denom
    target_world = cam_pos_world.flatten() + s * ray_world.flatten()
    
    return target_world[0], target_world[1], target_world[2]



def on_click(event, u, v, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        # Scale back to 1080p
        u_real = int(u * (1920 / 1280))
        v_real = int(v * (1080 / 720))
        
        coords = pixel_to_robot_3d(u_real, v_real, CURRENT_THICKNESS)
        if coords:
            # Apply the "Final Polish" offsets
            rx = coords[0] + X_OFFSET
            ry = coords[1] + Y_OFFSET
            
            # THE SAFETY FIX: Ignore the math's Z and force a safe, flat Z height!
            # -48.0 leaves it hovering about 2mm above the table so it won't crash.
            rz = -48.0 + CURRENT_THICKNESS  # Adjust Z if needed based on your thickness

            print(f"Click: ({u_real},{v_real}) -> Robot Target: X:{rx:.2f}, Y:{ry:.2f}, Z:{rz:.2f}")

            # Calculate Distance from Base (Pythagoras)
            dist = np.sqrt(rx**2 + ry**2)
            
            # Dobot Magician Safe Zone
            if 160 < dist < 330:
                # IMPORTANT: Clear the queue to ensure immediate response
                dType.SetQueuedCmdClear(api)
                
                # Move sequence
                dType.SetPTPCmd(api, dType.PTPMode.PTPMOVJXYZMode, rx, ry, rz + 20, 0, isQueued=1)
                dType.SetPTPCmd(api, dType.PTPMode.PTPMOVLXYZMode, rx, ry, rz, 0, isQueued=1)
                
                # Add a small delay/wait so you can see if it hit the spot
                dType.SetWAITCmd(api, 500, isQueued=1) 
                
                dType.SetPTPCmd(api, dType.PTPMode.PTPMOVJXYZMode, rx, ry, rz + 20, 0, isQueued=1)
            else:
                print(f"SKIP: Physical Limit Reached ({dist:.1f}mm)")

# 3. MAIN LOOP
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cv2.namedWindow("Dobot Vision Control")
cv2.setMouseCallback("Dobot Vision Control", on_click)

while True:
    ret, frame = cap.read()
    if not ret:
        break
    
    # Rectify the frame so the clicks match our math
    rectified = cv2.undistort(frame, mtx, dist)
    
    cv2.putText(rectified, "CLICK TO MOVE ARM", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
    cv2.imshow("Dobot Vision Control", cv2.resize(rectified, (1280, 720)))
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

dType.DisconnectDobot(api)
cap.release()
cv2.destroyAllWindows()