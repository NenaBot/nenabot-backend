import sys
import os
import time

# Ensure Python can find your app folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.adapters.robot import RobotAdapter

# =======================================================================
# 1. THE OAK TREE (Your exact desk coordinates)
# =======================================================================
MARKER_ROBOT_X = 125.4  
MARKER_ROBOT_Y = 240.3  

# =======================================================================
# 2. THE TARGET (From the photo you uploaded earlier!)
# =======================================================================
BATTERY_OFFSET_X = 208.9
BATTERY_OFFSET_Y = -38.7

# Heights
SAFE_Z_HEIGHT = 10.0 
WORKING_Z_HEIGHT = -43.6 

def test_full_translation_run():
    print("\n--- Starting the Robot-Only Translator ---")
    robot = RobotAdapter()
    
    print("Connecting to Robot...")
    robot_res = robot.connect_first_available()
    assert robot_res.ok is True, f"Robot failed to connect! {robot_res.error}"
    time.sleep(2)
    
    print("Hovering over the marker...")
    robot.move(x=MARKER_ROBOT_X, y=MARKER_ROBOT_Y, z=SAFE_Z_HEIGHT, r=0.0)
    time.sleep(2)

    # 3. THE TRANSLATOR MATH (No camera needed!)
    target_x = MARKER_ROBOT_X + BATTERY_OFFSET_X
    target_y = MARKER_ROBOT_Y + BATTERY_OFFSET_Y
    
    print(f"\n--- TRANSLATION COMPLETE ---")
    print(f"Driving robot to Target Coordinates -> X: {target_x:.1f}, Y: {target_y:.1f}")

    # 4. The Claw Machine Movement
    print("Moving OVER the battery...")
    robot.move(x=target_x, y=target_y, z=SAFE_Z_HEIGHT, r=0.0)
    time.sleep(3) 
    
    print("Dropping DOWN to touch the desk...")
    robot.move(x=target_x, y=target_y, z=WORKING_Z_HEIGHT, r=0.0)
    time.sleep(2)
    
    print("Moving back UP to safe height...")
    robot.move(x=target_x, y=target_y, z=SAFE_Z_HEIGHT, r=0.0)
    time.sleep(2)
    
    print("\nMission Accomplished! Disconnecting.")
    robot.disconnect()