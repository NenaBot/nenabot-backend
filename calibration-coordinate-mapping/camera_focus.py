# This code is designed to open the camera settings menu on Windows when using OpenCV. By default, OpenCV may not trigger the camera settings menu due to how it interfaces with the camera drivers. The key is to specify the backend for video capture, in this case, DirectShow (CAP_DSHOW), which allows access to the camera settings.


import cv2

# The magic fix: add cv2.CAP_DSHOW to force DirectShow!
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

# Now this line should actually trigger the Windows menu
cap.set(cv2.CAP_PROP_SETTINGS, 1)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    cv2.imshow("Camera View", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):

        break

cap.release()
cv2.destroyAllWindows()
