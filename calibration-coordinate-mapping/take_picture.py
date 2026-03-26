# This code is designed to capture images of a chessboard pattern using a webcam for the purpose of camera calibration. It automatically detects the chessboard corners in the video feed and allows you to save images when the corners are successfully detected. The saved images will be used later for calibrating the camera to correct for lens distortion and to understand the camera's perspective (intrinsic-calibration.py). Make sure to print an A3-sized chessboard pattern with 9x7 squares (8x6 inner corners) and use it during the capture process for accurate calibration results.

import cv2
import os
import sys

print("Script starting...")
print(f"OpenCV version: {cv2.__version__}")

# 1. Configuration: Match your A3 print (9x7 squares = 8x6 inner corners)
CHESSBOARD_SIZE = (8, 6)
SAVE_PATH = "calibration_images"

# Create folder if it doesn't exist
if not os.path.exists(SAVE_PATH):
    os.makedirs(SAVE_PATH)

# 2. Try to open a camera — attempt index 0, 1, and 2
#    Using DirectShow backend (cv2.CAP_DSHOW) to avoid MSMF freezing on Windows
cap = None
for cam_index in [0, 1, 2]:
    print(f"Trying camera index {cam_index} (DirectShow)...")
    test_cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
    if test_cap.isOpened():
        ret, frame = test_cap.read()
        if ret:
            print(f"  -> Camera {cam_index} works!")
            cap = test_cap
            break
        else:
            print(f"  -> Camera {cam_index} opened but could not read a frame.")
            test_cap.release()
    else:
        print(f"  -> Camera {cam_index} could not be opened.")

if cap is None:
    print("\nERROR: No working camera found!")
    print("Make sure your camera is connected and not used by another application.")
    input("Press Enter to exit...")
    sys.exit(1)

# Set high resolution for better precision (adjust to camera's max, avoid change it))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

print(f"Camera opened: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
print("--- Chessboard Capture Started ---")
print("Press 's' to Save an image when corners are detected.")
print("Press 'q' to Quit.")

# Create a resizable window so the display fits on screen
cv2.namedWindow("Calibration Capture", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Calibration Capture", 960, 540)

count = 0
while True:
    ret, frame = cap.read()
    if not ret:
        print("ERROR: Failed to read frame from camera. Camera may have disconnected.")
        break

    # Work on a grayscale copy for detection
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 3. Find Chessboard Corners
    # This is the 'Automatic Detection' core 
    found, corners = cv2.findChessboardCorners(gray, CHESSBOARD_SIZE, None)

    # Copy of frame to show visual feedback
    display_frame = frame.copy()

    if found:
        # 4. Draw corners so you know it's working
        cv2.drawChessboardCorners(display_frame, CHESSBOARD_SIZE, corners, found)
        cv2.putText(display_frame, "READY TO SAVE (Press 's')", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    else:
        cv2.putText(display_frame, "Searching for board...", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    cv2.imshow("Calibration Capture", display_frame)

    key = cv2.waitKey(1) & 0xFF
    
    # 5. Save Logic
    if key == ord('s') and found:
        count += 1
        file_name = os.path.join(SAVE_PATH, f"calib_{count:02d}.png")
        cv2.imwrite(file_name, frame) # Save the RAW frame, not the one with lines
        print(f"Saved: {file_name}")

    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print(f"Done! You have saved {count} images in the '{SAVE_PATH}' folder.")
input("Press Enter to exit...")