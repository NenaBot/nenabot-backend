from app.adapters.camera_vision import CameraVisionAdapter

print("Starting Camera Vision Test...")

# 1. Initialize the camera (This will load your calibration.json and lock focus to 43)
vision = CameraVisionAdapter()

# 2. Trigger the capture (This takes the picture and applies the "ironing" math)
print("Capturing image...")
capture_result = vision.capture()

if not capture_result.ok:
    print(f"Capture failed: {capture_result.error}")
else:
    print(f"Success! Ironed image saved to: {capture_result.image_path}")
    
    # 3. Trigger the detection (This finds the ArUco marker and calculates millimeters)
    print("Detecting targets...")
    detection_result = vision.detect(capture_result.image_path)
    
    if not detection_result.ok:
        print(f"Detection failed: {detection_result.error}")
    else:
        print("\n--- DETECTION RESULTS ---")
        for i, target in enumerate(detection_result.detections):
            print(f"Target {i+1}:")
            print(f"  Center X,Y (pixels): {target.center_x:.1f}, {target.center_y:.1f}")
            print(f"  Width x Height:      {target.width_mm:.1f} x {target.height_mm:.1f} mm")
            print(f"  Distance from ArUco: X = {target.offset_x_mm:.1f} mm, Y = {target.offset_y_mm:.1f} mm\n")