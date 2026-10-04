"""Master Focus Agent Coordinator.

Ties together:
1. OpenCV Doomscroll Detector (detects phone usage / looking down)
2. FreeWili Target Goal Synchronizer (syncs jumping jack goal to FreeWili screen)
3. FreeWili I2S Audio Streaming (plays officer alarms and drill sergeant audio directly on FreeWili speaker)
4. FreeWili Telemetry Client (verifies physical jumping jacks via accelerometer)
"""

import argparse
import logging
import random
import time
import cv2
import numpy as np

from doomscroll_detector import DoomscrollDetector
from freewili_client import FreeWiliClient, FreeWiliTelemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FocusAgent")

# Vocal Drill Sergeant Speech IDs matching FreeWili firmware (drill_sergeant_audio.h)
VOICE_SWIVEL_NECK = 1   # "Did somebody tell you to swivel your neck, private? Ocular reconnaissance..."
VOICE_PUSH_PLANET = 2   # "Down! Get on your face right now! Push 'em out! You are pushing that planet..."
VOICE_HEAVY_BOOTS = 3   # "On your back, flutter kicks! Point your toes! Are your boots too heavy..."
VOICE_SLUG_SPRINT = 4   # "Faster, private! I have seen slugs sprint faster than that!..."
VOICE_DISMISSED   = 5   # "Attention! Penalty cleared! Lock in! Dismissed!"



class FocusAgent:
    def __init__(
        self,
        target_jumps: int = 10,
        trigger_sec: float = 3.5,
        volume: int = 100,
        presage_api_key: str = None,
        presage_enabled: bool = True,
    ):
        if not presage_api_key:
            try:
                from settings_manager import get_default_api_key
                presage_api_key = get_default_api_key()
            except Exception:
                import os
                presage_api_key = os.getenv("PRESAGE_API_KEY") or os.getenv("SMARTSPECTRA_API_KEY") or ""
        self.target_jumps = target_jumps
        self.volume = max(0, min(100, volume))
        self.penalty_active = False
        self.penalty_start_count = 0
        self.jumps_completed_in_penalty = 0

        self.detector = DoomscrollDetector(
            trigger_duration_sec=trigger_sec,
            presage_api_key=presage_api_key,
            presage_enabled=presage_enabled,
        )
        self.freewili = FreeWiliClient(on_telemetry=self.on_freewili_telemetry)
        self.freewili.latest_telemetry.target = target_jumps

        self.last_audio_alert = 0.0

    def on_freewili_telemetry(self, t: FreeWiliTelemetry):
        if self.penalty_active:
            # Track jumps performed since penalty started
            self.jumps_completed_in_penalty = max(0, t.jumps - self.penalty_start_count)

            if self.jumps_completed_in_penalty >= self.target_jumps:
                logger.info(f"Target completed! ({self.jumps_completed_in_penalty}/{self.target_jumps})")
                self.penalty_active = False
                self.detector.reset_penalty()
                # Play Dismissal speech through FreeWili I2S speaker
                logger.info("Penalty cleared! Playing drill sergeant dismissal voice on FreeWili speaker.")
                self.freewili.play_sound(VOICE_DISMISSED)
            elif t.state_name == "LANDED":
                logger.info(f"Rep recorded: {self.jumps_completed_in_penalty}/{self.target_jumps} (G: {t.g_mg}mg)")

    def trigger_penalty(self):
        if not self.penalty_active:
            self.penalty_active = True
            self.penalty_start_count = self.freewili.latest_telemetry.jumps
            self.jumps_completed_in_penalty = 0
            logger.warning(f"DOOMSCROLLING PENALTY TRIGGERED! Syncing target {self.target_jumps} to FreeWili.")

            # 1. Sync jumping jack target to FreeWili screen & counter
            self.freewili.set_target(self.target_jumps)

            # 2. Blast Drill Sergeant 'Swivel Neck / Ocular Reconnaissance' Speech directly on FreeWili waist speaker
            self.freewili.play_sound(VOICE_SWIVEL_NECK)
            self.last_audio_alert = time.time()

    def run(self, camera_idx: int = 0):
        cap = cv2.VideoCapture(camera_idx)
        if not cap.isOpened():
            logger.error(f"Cannot open webcam index {camera_idx}")
            return

        print("\n" + "=" * 65)
        print("  FOCUS AGENT: DOOMSCROLL SENTINEL & FREEWILI JUMP VERIFIER")
        print("=" * 65)
        print("  - Strapped to waist: FreeWili OG (LIS3DH + MAX98357A I2S Speaker)")
        print("  - Wireless Bridge: Bottlenose Orca (ESP32-C6) over BLE")
        print(f"  - Synchronized Jumping Jack Goal: {self.target_jumps} Reps")
        print(f"  - Synchronized Speaker Volume: {self.volume}% (High-Gain Boost)")
        print("  - Audio Destination: FREEWILI ONBOARD SPEAKER (Vocal Drill Sergeant)")
        print("  - Press 'q' in the camera window to quit.")
        print("=" * 65 + "\n")

        # Initial target and volume synchronization packets
        time.sleep(0.5)
        self.freewili.set_target(self.target_jumps)
        time.sleep(0.1)
        self.freewili.set_volume(self.volume)

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Mirror image for natural user preview
            frame = cv2.flip(frame, 1)

            # Process frame through OpenCV detector
            frame, is_doomscroll, duration_down = self.detector.process_frame(frame)

            if is_doomscroll and not self.penalty_active:
                self.trigger_penalty()

            # Cycle motivational reprimands on FreeWili speaker every 14 seconds if still in penalty
            if self.penalty_active and (time.time() - self.last_audio_alert > 14.0):
                self.last_audio_alert = time.time()
                drill_line = random.choice([VOICE_PUSH_PLANET, VOICE_HEAVY_BOOTS, VOICE_SLUG_SPRINT])
                logger.info(f"Broadcasting drill voice line #{drill_line} to FreeWili speaker...")
                self.freewili.play_sound(drill_line)

            # Render Penalty HUD
            self._draw_penalty_hud(frame)

            cv2.imshow("Focus Agent - Doomscroll Sentinel", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        cv2.destroyAllWindows()
        self.detector.release()
        self.freewili.stop()

    def _draw_penalty_hud(self, frame: np.ndarray):
        h, w = frame.shape[:2]

        # FreeWili connection & telemetry widget at bottom
        widget = frame.copy()
        cv2.rectangle(widget, (0, h - 85), (w, h), (15, 20, 30), -1)
        cv2.addWeighted(widget, 0.85, frame, 0.15, 0, frame)

        t = self.freewili.latest_telemetry
        conn_str = "CONNECTED" if self.freewili.is_connected else "DISCONNECTED"
        conn_color = (0, 255, 120) if self.freewili.is_connected else (0, 160, 255)

        cv2.putText(
            frame,
            f"FreeWili: {conn_str} | Goal: {self.target_jumps} | State: {t.state_name} (G: {t.g_mg}mg)",
            (20, h - 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            conn_color,
            1,
            cv2.LINE_AA,
        )

        if self.penalty_active:
            rem = max(0, self.target_jumps - self.jumps_completed_in_penalty)
            rep_text = f"PENALTY: DO {rem} MORE JUMPING JACKS! ({self.jumps_completed_in_penalty}/{self.target_jumps}) [SPEAKER ACTIVE]"
            cv2.putText(
                frame,
                rep_text,
                (20, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 80, 255),
                2,
                cv2.LINE_AA,
            )
        else:
            cv2.putText(
                frame,
                f"FOCUS SECURE: NO PHONE ACTIVITY DETECTED (GOAL SYNCED: {self.target_jumps})",
                (20, h - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 120),
                1,
                cv2.LINE_AA,
            )


def main():
    parser = argparse.ArgumentParser(description="Focus Agent: Doomscroll Sentinel & Jumping Jack Enforcer")
    parser.add_argument("--mode", choices=["ble", "serial", "mock"], default="mock",
                        help="Connection mode to FreeWili: 'ble' (Bottlenose Orca), 'serial' (USB COM), or 'mock'")
    parser.add_argument("--port", type=str, default="COM3", help="Serial port for --mode serial")
    parser.add_argument("--target", type=int, default=10, help="Number of jumping jacks required upon penalty")
    parser.add_argument("--volume", type=int, default=100, help="FreeWili speaker volume percentage (0-100%%, default 100)")
    parser.add_argument("--cam", type=int, default=0, help="Webcam device index")
    args = parser.parse_args()

    agent = FocusAgent(target_jumps=args.target, volume=args.volume)

    if args.mode == "ble":
        print("[FocusAgent] Launching BLE scanner for Bottlenose Orca...")
        agent.freewili.start_ble()
    elif args.mode == "serial":
        print(f"[FocusAgent] Connecting via USB serial to {args.port}...")
        agent.freewili.start_serial(args.port)
    else:
        print("[FocusAgent] Running in MOCK mode (simulated jumps).")
        agent.freewili.start_mock(jumps_per_min=45)

    agent.run(camera_idx=args.cam)


if __name__ == "__main__":
    main()
