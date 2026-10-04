"""Settings Manager for Focus Agent Desktop Application.

Persists user configurations such as jumping jack goal, connection mode,
speaker output preference, and FreeWili volume.
"""

import json
import os
import sys

def load_env_file():
    """Load environment variables from .env file across project or app paths."""
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.path.dirname(sys.executable), ".env"),
    ]
    app_data = os.getenv("APPDATA")
    if app_data:
        candidates.append(os.path.join(app_data, "FreeWiliFocusAgent", ".env"))
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        candidates.append(os.path.join(base_dir, ".env"))

    for c in candidates:
        if os.path.isfile(c):
            try:
                from dotenv import load_dotenv
                load_dotenv(c, override=False)
            except Exception:
                try:
                    with open(c, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                k, v = k.strip(), v.strip().strip("\"'")
                                if k and k not in os.environ:
                                    os.environ[k] = v
                except Exception:
                    pass
            break


def get_default_api_key() -> str:
    """Retrieve Presage API key from environment variable or .env file."""
    load_env_file()
    return os.getenv("PRESAGE_API_KEY") or os.getenv("SMARTSPECTRA_API_KEY") or ""


def get_default_settings() -> dict:
    """Return default settings dictionary with Presage key resolved from .env."""
    return {
        "target_jumps": 10,
        "connection_mode": "ble",     # "ble", "serial", "mock"
        "serial_port": "COM3",
        "speaker_output": "laptop",    # "laptop", "freewili"
        "freewili_volume": 100,       # 0 - 100%
        "camera_index": 0,
        "trigger_duration_sec": 3.5,
        "auto_minimize_on_start": False,
        "presage_enabled": True,
        "presage_api_key": get_default_api_key(),
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
    defaults = get_default_settings()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                settings = dict(defaults)
                settings.update(data)
                # If settings.json has empty key, pull from .env
                if not settings.get("presage_api_key"):
                    settings["presage_api_key"] = defaults.get("presage_api_key", "")
                return settings
        except Exception:
            pass
    return dict(defaults)


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
