import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import cv2
import numpy as np
from app.adapters.camera_vision import CameraVisionAdapter

def test_live_hardware_capture_and_detect():
    adapter = CameraVisionAdapter(device_index=0, marker_size_mm=48.0)
    
    print("\n--- Triggering camera. Make sure the battery is in view! ---")
    capture_result = adapter.capture()
    assert capture_result.ok is True, f"Camera failed: {capture_result.error}"
    
    detect_result = adapter.detect(capture_result.image_path)
    assert detect_result.ok is True, f"Detection failed: {detect_result.error}"
    print(f"Found {len(detect_result.detections)} battery/batteries!")
    
    # --- NEW: Get out our virtual Sharpie marker ---
    # 1. Open the picture we just took
    img = cv2.imread(capture_result.image_path)
    
    # 2. Draw a dot and the text for every battery we found
    for battery in detect_result.detections:
        center = (int(battery.center_x), int(battery.center_y))
        
        # Draw a red dot in the middle of the battery
        cv2.circle(img, center, 5, (0, 0, 255), -1)
        
        # Write the X and Y coordinates in green text
        text = f"X: {battery.offset_x_mm:.1f} Y: {battery.offset_y_mm:.1f}"
        cv2.putText(img, text, (center[0] - 50, center[1] - 20), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        print(f"Battery located at: {text}")

    # 3. Save a new copy of the picture with our drawings on it
    annotated_path = capture_result.image_path.replace(".jpg", "_annotated.jpg")
    cv2.imwrite(annotated_path, img)
    print(f"Saved map with Sharpie drawings to: {annotated_path}")