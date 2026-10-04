"""OpenCV-based Doomscroll & Posture Detector.

Monitors user face orientation and posture using laptop webcam:
- Tracks face and eye bounding boxes
- Calculates head down tilt and gaze deviation
- Measures continuous duration spent looking down at phone
- Triggers DOOMSCROLL_ALERT when duration exceeds threshold
"""

import time
from typing import Tuple, Optional
import cv2
import numpy as np


class DoomscrollDetector:
    def __init__(self, trigger_duration_sec: float = 3.5):
        self.trigger_duration_sec = trigger_duration_sec
        self.look_down_start: Optional[float] = None
        self.is_doomscrolling = False

        # Load OpenCV Haar Cascades
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )

        self.last_face_y: Optional[float] = None
        self.baseline_face_y: Optional[float] = None

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, bool, float]:
        """
        Process a video frame and return:
        - annotated_frame
        - is_doomscrolling (bool)
        - duration looking down (seconds)
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80)
        )

        looking_down = False
        duration_down = 0.0

        if len(faces) > 0:
            # Track primary (largest) face
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            (x, y, fw, fh) = faces[0]

            # Draw face box
            cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 255, 120), 2)

            face_center_y = y + (fh / 2.0)
            if self.baseline_face_y is None:
                self.baseline_face_y = face_center_y
            else:
                # Slowly adapt baseline when user is in upright posture
                self.baseline_face_y = 0.98 * self.baseline_face_y + 0.02 * face_center_y

            # Search for eyes in top half of face
            roi_gray = gray[y : y + int(fh * 0.65), x : x + fw]
            eyes = self.eye_cascade.detectMultiScale(
                roi_gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20)
            )

            for (ex, ey, ew, eh) in eyes:
                cv2.rectangle(
                    frame,
                    (x + ex, y + ey),
                    (x + ex + ew, y + ey + eh),
                    (255, 200, 0),
                    1,
                )

            # Heuristics for looking down:
            # 1. Face dropped significantly lower than baseline (head bowed downward)
            # 2. Or eyes are no longer visible in frontal cascade while face is lower
            drop_ratio = (face_center_y - self.baseline_face_y) / float(fh)
            
            if drop_ratio > 0.22 or (len(eyes) == 0 and drop_ratio > 0.12):
                looking_down = True
        else:
            # User face dropped below camera frame completely (looking down at phone in lap)
            if self.baseline_face_y is not None:
                looking_down = True

        # Temporal accumulation
        now = time.time()
        if looking_down:
            if self.look_down_start is None:
                self.look_down_start = now
            duration_down = now - self.look_down_start

            if duration_down >= self.trigger_duration_sec:
                self.is_doomscrolling = True
        else:
            # User restored focus
            self.look_down_start = None
            duration_down = 0.0

        # Render HUD Overlay
        self._render_hud(frame, duration_down, looking_down)

        return frame, self.is_doomscrolling, duration_down

    def reset_penalty(self):
        """Called when user successfully completes jumping jacks."""
        self.is_doomscrolling = False
        self.look_down_start = None

    def _render_hud(self, frame: np.ndarray, duration_down: float, looking_down: bool):
        h, w = frame.shape[:2]
        overlay = frame.copy()

        # Header banner
        cv2.rectangle(overlay, (0, 0), (w, 50), (20, 20, 30), -1)

        if self.is_doomscrolling:
            status_text = "PENALTY ACTIVE: DOOMSCROLL DETECTED!"
            status_color = (0, 0, 255)
        elif looking_down:
            status_text = f"WARNING: LOOKING DOWN ({duration_down:.1f}s / {self.trigger_duration_sec:.1f}s)"
            status_color = (0, 180, 255)
        else:
            status_text = "STATUS: FOCUSED"
            status_color = (0, 255, 120)

        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
        cv2.putText(
            frame,
            status_text,
            (20, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            status_color,
            2,
            cv2.LINE_AA,
        )


if __name__ == "__main__":
    detector = DoomscrollDetector(trigger_duration_sec=3.0)
    cap = cv2.VideoCapture(0)
    print("Starting doomscroll detector demo. Press 'q' to exit.")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame, alert, dur = detector.process_frame(frame)
        cv2.imshow("Doomscroll Detector", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
