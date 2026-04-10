# This code is designed to be run on a PC that is connected to the Dobot arm via USB. It allows you to manually move the arm to specific points on the chessboard, and then captures the robot's coordinates for those points. The collected data will be used in the next step (mapping-matrix.py) to calculate the transformation matrix between camera space and robot space.
# Make sure to follow the instructions carefully, and ensure that the Dobot arm is properly connected and recognized by your computer before running this code.

import DobotDllType as dType

# 1. Initialize and Connect
api = dType.load()
CON_STR = {
    dType.DobotConnect.DobotConnect_NoError:  "Success",
    dType.DobotConnect.DobotConnect_NotFound: "NotFound",
    dType.DobotConnect.DobotConnect_Occupied: "Occupied"
}

state = dType.ConnectDobot(api, "COM5", 115200)[0]  # replace COM3 with actual port

print(f"Connect status: {CON_STR.get(state, 'Unknown Error')}")

if state != dType.DobotConnect.DobotConnect_NoError:
    print("Could not connect. Check USB and make sure DobotStudio is closed.")
    exit()

def get_dobot_pose():
    # dType.GetPose returns [x, y, z, r, j1, j2, j3, j4]
    pose = dType.GetPose(api)
    return pose[0], pose[1], pose[2]

# 2. Collection Loop
points_list = []
print("\n" + "="*40)
print("DOBOT CALIBRATION POINT COLLECTOR")
print("="*40)
print("Instructions:")
print("1. Press the UNLOCK button on the Dobot arm.")
print("2. Move the tip to the chessboard intersection.")
print("3. Come back to the PC to record data.")

for i in range(1, 5):
    print(f"\n--- COLLECTING POINT {i} ---")
    row = input(f"Enter the Row index for Point {i} (0-5): ")
    col = input(f"Enter the Column index for Point {i} (0-7): ")
    
    input("Position the arm and press [ENTER] to capture coordinates...")
    x, y, z = get_dobot_pose()
    
    print(f"-> Captured: X={x:.2f}, Y={y:.2f}, Z={z:.2f}")
    
    points_list.append({
        "grid_index": [int(row), int(col)],
        "robot_coords": [x, y, z]
    })

# 3. Disconnect
dType.DisconnectDobot(api)

# 4. Final Output for the math step
print("\n" + "="*40)
print("COPY AND PASTE THIS DATA TO mapping-matrix.py file")
print("="*40)
for p in points_list:
    print(p)