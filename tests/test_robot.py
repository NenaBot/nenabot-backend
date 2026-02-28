import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.adapters.robot import RobotAdapter

def test_live_robot_movement():
    adapter = RobotAdapter()
    
    # 1. Establish the Handshake
    print("\n--- Powering on Robot Arm ---")
    conn_res = adapter.connect_first_available()
    assert conn_res.ok is True, f"Failed to connect: {conn_res.error}"
    print(f"Success! Connected to port: {adapter._connected_port}")
    
    # 2. Calibrate (Home)
    # WARNING: Stand back! The arm will swing to its mechanical zero position.
    print("--- Homing the arm (stand back!) ---")
    adapter.home()
    time.sleep(15) # Give the physical motors time to finish the homing sequence
    
    # 3. Send the Move Signal
    print("--- Moving to safe hover position (X:200, Y:0, Z:50) ---")
    move_res = adapter.move(x=200, y=0, z=50, r=0)
    assert move_res.ok is True, f"Move command failed: {move_res.error}"
    time.sleep(5) # Let it finish moving
    
    # 4. Safe Shutdown
    print("--- Disconnecting ---")
    adapter.disconnect()
    
def test_read_robot_position():
    adapter = RobotAdapter()
    
    print("\n--- Powering on Robot Arm ---")
    conn_res = adapter.connect_first_available()
    assert conn_res.ok is True, "Failed to connect!"
    
    print("\n=======================================================")
    print("1. Press and hold the UNLOCK button on the robot arm.")
    print("2. Manually drag the tip to the EXACT CENTER of the ArUco marker.")
    print("3. Hold it there! You have 15 seconds... Go!")
    print("=======================================================")
    
    # Give you 15 seconds to move the arm
    time.sleep(15) 
    
    # Read the coordinates
    x, y, z = adapter.get_pose()
    
    print("\n*******************************************************")
    print(f"OAK TREE FOUND AT ROBOT COORDINATES: X: {x:.1f}, Y: {y:.1f}, Z: {z:.1f}")
    print("*******************************************************")
    
    adapter.disconnect()