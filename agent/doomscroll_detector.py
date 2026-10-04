"""High-Accuracy Deep Learning Doomscroll & Posture Detector.

Utilizes OpenCV YuNet 5-landmark face detection (with Haar cascade fallback):
- Real-time 3D/2D vertical pitch ratio (eye-to-nose vs nose-to-mouth compression)
- Relative vertical nose displacement within face bounding box
- Vertical slouch / lap phone look-down tracking
- Temporal debounce accumulation and penalty trigger
"""

import os
import sys
import time
from typing import Tuple, Optional
import cv2
import numpy as np


def get_model_path(model_name: str) -> Optional[str]:
    """Locate model asset in both standard development and PyInstaller bundled environments."""
    candidates = []
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        candidates.extend([
            os.path.join(base_dir, model_name),
            os.path.join(base_dir, "agent", model_name),
            os.path.join(base_dir, "data", model_name),
        ])
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.extend([
        os.path.join(here, model_name),
        os.path.join(here, "..", model_name),
        os.path.join(os.getcwd(), "agent", model_name),
        os.path.join(os.getcwd(), model_name),
    ])
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def get_cascade_path(xml_name: str) -> str:
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        for sub in ["cv2/data", "data", ""]:
            cand = os.path.join(base_dir, sub, xml_name) if sub else os.path.join(base_dir, xml_name)
            if os.path.isfile(cand):
                return cand
    try:
        cand = os.path.join(cv2.data.haarcascades, xml_name)
        if os.path.isfile(cand):
            return cand
    except Exception:
        pass
    return xml_name


class DoomscrollDetector:
    def __init__(self, trigger_duration_sec: float = 3.5):
        self.trigger_duration_sec = trigger_duration_sec
        self.look_down_start: Optional[float] = None
        self.last_look_down_time: float = 0.0
        self.is_doomscrolling = False

        # Baseline posture metrics
        self.baseline_face_y: Optional[float] = None
        self.baseline_pitch: Optional[float] = None
        self.baseline_nose_rel: Optional[float] = None
        self.last_seen_face_time: float = 0.0

        # 1. Initialize YuNet deep learning detector (ultra-lightweight, 5 landmarks)
        self.yunet = None
        yunet_path = get_model_path("face_detection_yunet_2023mar.onnx")
        if yunet_path and hasattr(cv2, "FaceDetectorYN"):
            try:
                self.yunet = cv2.FaceDetectorYN.create(
                    model=yunet_path,
                    config="",
                    input_size=(640, 480),
                    score_threshold=0.55,
                    nms_threshold=0.3,
                    top_k=5000,
                )
            except Exception:
                self.yunet = None

        # 2. Fallback Haar Cascades (configured for small & angled faces)
        self.face_cascade = cv2.CascadeClassifier(
            get_cascade_path("haarcascade_frontalface_alt2.xml")
        )
        if self.face_cascade.empty():
            self.face_cascade = cv2.CascadeClassifier(
                get_cascade_path("haarcascade_frontalface_default.xml")
            )
        self.eye_cascade = cv2.CascadeClassifier(
            get_cascade_path("haarcascade_eye.xml")
        )

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, bool, float]:
        """
        Process incoming webcam frame:
        Returns (annotated_frame, is_doomscrolling, duration_down)
        """
        h, w = frame.shape[:2]
        now = time.time()

        face_detected = False
        looking_down = False
        pitch_val = 1.0

        # ---------------------------------------------------------
        # Strategy A: YuNet 5-Landmark Deep Learning Detection
        # ---------------------------------------------------------
        if self.yunet is not None:
            try:
                self.yunet.setInputSize((w, h))
                _, faces = self.yunet.detect(frame)
                if faces is not None and len(faces) > 0:
                    # Select largest confident face
                    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                    face = faces[0]
                    box = face[0:4].astype(int)
                    bx, by, bw, bh = box[0], box[1], box[2], box[3]

                    # Clamp box inside frame
                    bx = max(0, min(w - 1, bx))
                    by = max(0, min(h - 1, by))
                    bw = max(1, min(w - bx, bw))
                    bh = max(1, min(h - by, bh))

                    re = face[4:6]  # Right eye (from person perspective)
                    le = face[6:8]  # Left eye
                    nose = face[8:10]
                    rm = face[10:12] # Mouth right
                    lm = face[12:14] # Mouth left

                    eye_y = (re[1] + le[1]) / 2.0
                    mouth_y = (rm[1] + lm[1]) / 2.0
                    nose_y = nose[1]
                    face_center_y = by + (bh / 2.0)

                    # Calculate vertical landmark distances
                    d_eye_nose = max(0.1, nose_y - eye_y)
                    d_nose_mouth = max(0.1, mouth_y - nose_y)

                    # Pitch ratio: when head tilts down, nose moves down towards mouth,
                    # so d_nose_mouth compresses and pitch_ratio increases significantly (>1.65)
                    pitch_val = float(d_eye_nose / max(1.0, d_nose_mouth))
                    nose_rel_y = float((nose_y - by) / float(bh))

                    face_detected = True
                    self.last_seen_face_time = now

                    # Vertical drop ratio relative to upright baseline
                    drop_ratio = 0.0
                    if self.baseline_face_y is not None:
                        drop_ratio = (face_center_y - self.baseline_face_y) / float(bh)

                    # Look-down criteria:
                    # 1. Pitch angle tilted downward (pitch_ratio > 1.65)
                    # 2. Nose pushed into bottom third of face box (nose_rel_y > 0.65)
                    # 3. Head slouched significantly downward into lap (drop_ratio > 0.18)
                    if pitch_val > 1.65 or nose_rel_y > 0.65 or drop_ratio > 0.18:
                        looking_down = True

                    # Upright baseline adaptation
                    if self.baseline_face_y is None:
                        self.baseline_face_y = face_center_y
                        self.baseline_pitch = pitch_val
                        self.baseline_nose_rel = nose_rel_y
                    elif not looking_down:
                        # Smooth adaptation towards upright posture
                        if face_center_y < self.baseline_face_y:
                            self.baseline_face_y = 0.85 * self.baseline_face_y + 0.15 * face_center_y
                        else:
                            self.baseline_face_y = 0.995 * self.baseline_face_y + 0.005 * face_center_y
                        self.baseline_pitch = 0.99 * self.baseline_pitch + 0.01 * pitch_val

                    # Draw sleek tactical corner brackets
                    box_col = (50, 50, 235) if (self.is_doomscrolling or looking_down) else (190, 195, 205)
                    corner_len = min(18, bw // 4, bh // 4)
                    cv2.line(frame, (bx, by), (bx + corner_len, by), box_col, 2)
                    cv2.line(frame, (bx, by), (bx, by + corner_len), box_col, 2)
                    cv2.line(frame, (bx + bw, by), (bx + bw - corner_len, by), box_col, 2)
                    cv2.line(frame, (bx + bw, by), (bx + bw, by + corner_len), box_col, 2)
                    cv2.line(frame, (bx, by + bh), (bx + corner_len, by + bh), box_col, 2)
                    cv2.line(frame, (bx, by + bh), (bx, by + bh - corner_len), box_col, 2)
                    cv2.line(frame, (bx + bw, by + bh), (bx + bw - corner_len, by + bh), box_col, 2)
                    cv2.line(frame, (bx + bw, by + bh), (bx + bw, by + bh - corner_len), box_col, 2)

                    # Draw subtle eye and nose landmark markers
                    cv2.circle(frame, (int(re[0]), int(re[1])), 2, (220, 225, 235), -1)
                    cv2.circle(frame, (int(le[0]), int(le[1])), 2, (220, 225, 235), -1)
                    cv2.circle(frame, (int(nose[0]), int(nose[1])), 2, box_col, -1)
            except Exception:
                face_detected = False

        # ---------------------------------------------------------
        # Strategy B: Haar Cascade Fallback
        # ---------------------------------------------------------
        if not face_detected:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)
                faces = self.face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=3, minSize=(25, 25)
                )
                if len(faces) > 0:
                    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                    (x, y, fw, fh) = faces[0]
                    face_detected = True
                    self.last_seen_face_time = now
                    face_center_y = y + (fh / 2.0)

                    # Corner reticles
                    box_col = (50, 50, 235) if (self.is_doomscrolling or looking_down) else (190, 195, 205)
                    corner_len = min(18, fw // 4, fh // 4)
                    cv2.line(frame, (x, y), (x + corner_len, y), box_col, 2)
                    cv2.line(frame, (x, y), (x, y + corner_len), box_col, 2)
                    cv2.line(frame, (x + fw, y), (x + fw - corner_len, y), box_col, 2)
                    cv2.line(frame, (x + fw, y), (x + fw, y + corner_len), box_col, 2)
                    cv2.line(frame, (x, y + fh), (x + corner_len, y + fh), box_col, 2)
                    cv2.line(frame, (x, y + fh), (x, y + fh - corner_len), box_col, 2)
                    cv2.line(frame, (x + fw, y + fh), (x + fw - corner_len, y + fh), box_col, 2)
                    cv2.line(frame, (x + fw, y + fh), (x + fw, y + fh - corner_len), box_col, 2)

                    drop_ratio = 0.0
                    if self.baseline_face_y is not None:
                        drop_ratio = (face_center_y - self.baseline_face_y) / float(fh)

                    if drop_ratio > 0.15:
                        looking_down = True

                    if self.baseline_face_y is None:
                        self.baseline_face_y = face_center_y
                    elif not looking_down:
                        if face_center_y < self.baseline_face_y:
                            self.baseline_face_y = 0.85 * self.baseline_face_y + 0.15 * face_center_y
                        else:
                            self.baseline_face_y = 0.995 * self.baseline_face_y + 0.005 * face_center_y
            except Exception:
                pass

        # If user was present recently (< 2.5s ago) and suddenly buried head in lap below camera:
        if not face_detected and (now - self.last_seen_face_time < 2.5) and (self.baseline_face_y is not None):
            looking_down = True

        # ---------------------------------------------------------
        # Temporal accumulation & debounce logic
        # ---------------------------------------------------------
        duration_down = 0.0
        if looking_down:
            self.last_look_down_time = now
            if self.look_down_start is None:
                self.look_down_start = now
            duration_down = now - self.look_down_start

            if duration_down >= self.trigger_duration_sec:
                self.is_doomscrolling = True
        else:
            if self.look_down_start is not None:
                # Brief flicker grace period (0.6s)
                if (now - self.last_look_down_time) < 0.6:
                    duration_down = now - self.look_down_start
                    if duration_down >= self.trigger_duration_sec:
                        self.is_doomscrolling = True
                else:
                    self.look_down_start = None
                    duration_down = 0.0
            else:
                duration_down = 0.0

        # Render HUD Overlay
        try:
            self._render_hud(frame, duration_down, looking_down, face_detected, pitch_val)
        except Exception:
            pass

        return frame, self.is_doomscrolling, duration_down

    def reset_penalty(self):
        """Reset penalty state upon workout completion or emergency bypass."""
        self.is_doomscrolling = False
        self.look_down_start = None
        self.last_look_down_time = 0.0

    def calibrate_baseline(self):
        """Recalibrate neutral posture."""
        self.baseline_face_y = None
        self.baseline_pitch = None
        self.baseline_nose_rel = None
        self.reset_penalty()

    def _render_hud(
        self,
        frame: np.ndarray,
        duration_down: float,
        looking_down: bool,
        face_detected: bool,
        pitch_val: float,
    ):
        h, w = frame.shape[:2]
        overlay = frame.copy()

        # Frosted Charcoal glass header bar
        cv2.rectangle(overlay, (0, 0), (w, 44), (16, 18, 22), -1)
        cv2.line(overlay, (0, 44), (w, 44), (45, 48, 58), 1)

        prog_col = (50, 50, 235)  # Crimson warning accent (BGR)

        if self.is_doomscrolling:
            status_text = "PENALTY ACTIVE // DOOMSCROLL DETECTED"
            pill_col = (20, 20, 140)
            text_col = (245, 245, 248)
            border_col = (50, 50, 235)
        elif looking_down:
            status_text = f"WARNING: HEAD DOWN ({duration_down:.1f}s / {self.trigger_duration_sec:.1f}s)"
            pill_col = (22, 28, 70)
            text_col = (245, 245, 248)
            border_col = (45, 75, 215)
        elif face_detected:
            status_text = f"SENTINEL ACTIVE // UPRIGHT POSTURE (Pitch: {pitch_val:.1f}x)"
            pill_col = (26, 28, 35)
            text_col = (225, 230, 238)
            border_col = (65, 70, 84)
        else:
            status_text = "SENTINEL ACTIVE // SEARCHING FOR USER FACE"
            pill_col = (24, 25, 30)
            text_col = (160, 165, 175)
            border_col = (50, 54, 65)

        # Draw status pill container with frosted border
        tw = int(cv2.getTextSize(status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 2)[0][0])
        px1, py1, px2, py2 = 14, 8, 28 + tw, 36
        cv2.rectangle(overlay, (px1, py1), (px2, py2), pill_col, -1)
        cv2.rectangle(overlay, (px1, py1), (px2, py2), border_col, 1)

        # Alpha composite frosted header
        cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)

        # Draw crisp anti-aliased status text
        cv2.putText(
            frame,
            status_text,
            (21, 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            text_col,
            2,
            cv2.LINE_AA,
        )

        # Countdown Progress Line below header if looking down
        if looking_down and duration_down > 0:
            ratio = min(1.0, duration_down / float(self.trigger_duration_sec))
            prog_w = int(w * ratio)
            cv2.line(frame, (0, 44), (prog_w, 44), prog_col, 2)
