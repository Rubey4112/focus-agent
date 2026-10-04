"""Settings Manager for Focus Agent Desktop Application.

Persists user configurations such as jumping jack goal, connection mode,
speaker output preference, and FreeWili volume.
"""

import json
import os
import sys

DEFAULT_SETTINGS = {
    "target_jumps": 10,
    "connection_mode": "ble",     # "ble", "serial", "mock"
    "serial_port": "COM3",
    "speaker_output": "laptop",    # "laptop", "freewili"
    "freewili_volume": 100,       # 0 - 100%
    "camera_index": 0,
    "trigger_duration_sec": 3.5,
    "auto_minimize_on_start": False,
}


def get_config_path() -> str:
    """Returns the persistent path to settings file."""
    # Place settings file in AppData or next to the exe
    app_data = os.getenv("APPDATA")
    if app_data:
        folder = os.path.join(app_data, "FreeWiliFocusAgent")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "settings.json")
    return "focus_agent_settings.json"


def load_settings() -> dict:
    """Load settings from JSON file or return defaults."""
    path = get_config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                settings = dict(DEFAULT_SETTINGS)
                settings.update(data)
                return settings
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> bool:
    """Save settings dictionary to JSON file."""
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        print(f"Failed to save settings: {e}", file=sys.stderr)
        return False
