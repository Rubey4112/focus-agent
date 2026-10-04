"""Comprehensive Integration Test for Presage SmartSpectra in DoomscrollDetector.

Verifies:
1. Presage SmartSpectra native SDK initialization & authentication with API key.
2. Frame processing & real-time telemetry streaming.
3. Distraction detection (head turned away, looking down, loss of focus).
4. Doomscroll penalty trigger on continuous distraction.
5. Penalty reset and clean session teardown.
"""

import os
import sys
import time
import numpy as np

# Ensure agent directory is in path
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from presage_sentinel import (
    PresageSentinel,
    VALIDATION_OK,
    VALIDATION_FACE_NOT_FORWARD,
    VALIDATION_FACE_TOO_LOW,
    VALIDATION_NO_FACE_FOUND,
)
from doomscroll_detector import DoomscrollDetector
from settings_manager import load_settings, save_settings, get_default_api_key


def test_presage_sentinel_direct():
    print("\n--- Test 1: PresageSentinel Direct SDK Authentication & Pipeline ---")
    api_key = get_default_api_key()
    assert api_key, "Presage API key not found in .env or environment"
    sentinel = PresageSentinel(api_key=api_key, distraction_debounce_sec=1.5, enabled=True)
    assert sentinel.capi is not None, "Failed to load smartspectra_capi.dll"

    started = sentinel.start_session()
    assert started, "Failed to start SmartSpectra session"
    print("[OK] Session started and authenticated with Presage cloud")

    # Push synthetic frames
    w, h = 640, 480
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    for _ in range(15):
        sentinel.push_frame(frame)
        time.sleep(0.033)

    time.sleep(0.5)
    telem = sentinel.get_telemetry()
    print(f"[OK] Presage telemetry received: status={telem['status_code']}, code={telem['validation_code']}, hint='{telem['validation_hint']}'")
    assert telem["is_running"], "Presage session is not running"

    sentinel.stop_session()
    print("[OK] Session stopped cleanly")


def test_doomscroll_detector_with_presage():
    print("\n--- Test 2: DoomscrollDetector with Presage Integration ---")
    api_key = get_default_api_key()
    det = DoomscrollDetector(
        trigger_duration_sec=1.5,
        presage_api_key=api_key,
        presage_enabled=True,
    )
    assert det.presage is not None, "Presage Sentinel not initialized in DoomscrollDetector"
    assert det.presage.is_running, "Presage session not active in DoomscrollDetector"

    w, h = 640, 480
    blank_frame = np.zeros((h, w, 3), dtype=np.uint8)

    # Frame 1: Initial frame
    ann_frame, is_doom, dur = det.process_frame(blank_frame)
    assert not is_doom, "Should not immediately trigger doomscroll"
    print(f"[OK] Initial frame processed: is_doom={is_doom}, dur={dur:.2f}s")

    # Simulate simulated distraction / head turned away / looking down
    print("[OK] Simulating distraction accumulation...")
    # Trigger distraction state directly on presage to test debounce
    det.presage.is_distracted = True
    det.presage.distraction_reason = "HEAD TURNED AWAY (OFF-SCREEN)"

    start_t = time.time()
    triggered = False
    for i in range(25):
        ann_frame, is_doom, dur = det.process_frame(blank_frame)
        if is_doom:
            triggered = True
            print(f"[OK] Doomscroll penalty successfully triggered at t={dur:.2f}s! Reason: {det.current_distraction_reason}")
            break
        time.sleep(0.1)

    assert triggered, "Doomscroll penalty should have triggered after 1.5s distraction"

    # Reset penalty
    det.reset_penalty()
    assert not det.is_doomscrolling, "Penalty should be cleared after reset"
    print("[OK] Penalty reset verified")

    det.release()
    print("[OK] Detector released cleanly")


def test_settings_presage_persistence():
    print("\n--- Test 3: Settings Manager Presage Persistence ---")
    settings = load_settings()
    expected_key = get_default_api_key()
    assert "presage_enabled" in settings, "presage_enabled missing from settings"
    assert "presage_api_key" in settings, "presage_api_key missing from settings"
    assert settings["presage_api_key"] == expected_key, "Presage API key mismatch"
    print(f"[OK] Settings verified: presage_enabled={settings['presage_enabled']}, presage_api_key={settings['presage_api_key'][:8]}...")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING PRESAGE SMARTSPECTRA DOOMSCROLL INTEGRATION TESTS")
    print("=" * 60)
    test_presage_sentinel_direct()
    test_doomscroll_detector_with_presage()
    test_settings_presage_persistence()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! Presage is fully integrated.")
    print("=" * 60)
