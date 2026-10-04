"""Audio Manager for Focus Agent.

Routes drill sergeant voice reprimands to either:
1. Laptop speakers via Windows winsound (crystal clear, high volume)
2. FreeWili OG onboard I2S speaker via Bluetooth / Serial commands
"""

import os
import sys
import logging
import random

logger = logging.getLogger("AudioManager")

# Audio Clip IDs
SOUND_SWIVEL_NECK = 1
SOUND_PUSH_PLANET = 2
SOUND_HEAVY_BOOTS = 3
SOUND_SLUG_SPRINT = 4
SOUND_PENALTY_CLEARED = 5

WAV_FILES = {
    SOUND_SWIVEL_NECK: "voice_swivel_neck.wav",
    SOUND_PUSH_PLANET: "voice_push_planet.wav",
    SOUND_HEAVY_BOOTS: "voice_heavy_boots.wav",
    SOUND_SLUG_SPRINT: "voice_slug_motivation.wav",
    SOUND_PENALTY_CLEARED: "voice_penalty_cleared.wav",
}


def get_asset_path(filename: str) -> str:
    """Resolve asset path whether running as script or PyInstaller bundle."""
    candidates = []
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir:
        candidates.extend([
            os.path.join(base_dir, "assets", "audio", filename),
            os.path.join(base_dir, "agent", "assets", "audio", filename),
            os.path.join(base_dir, filename),
        ])

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.extend([
        os.path.join(script_dir, "assets", "audio", filename),
        os.path.join(os.path.dirname(script_dir), "agent", "assets", "audio", filename),
        os.path.join(os.path.dirname(script_dir), "assets", "audio", filename),
        os.path.join(os.path.dirname(script_dir), "scratch_audio", filename),
        filename,
    ])

    for cand in candidates:
        if os.path.isfile(cand):
            return cand

    return candidates[0] if candidates else filename


class AudioManager:
    def __init__(self, freewili_client=None, output_destination: str = "laptop"):
        self.freewili = freewili_client
        self.output_destination = output_destination.lower()  # "laptop" or "freewili"

    def set_output_destination(self, dest: str):
        self.output_destination = dest.lower()

    def play(self, sound_id: int):
        """Play voice line through selected output device."""
        if self.output_destination == "freewili" and self.freewili:
            logger.info(f"Routing sound #{sound_id} to FreeWili speaker...")
            self.freewili.play_sound(sound_id)
        else:
            self._play_laptop(sound_id)

    def _play_laptop(self, sound_id: int):
        filename = WAV_FILES.get(sound_id)
        if not filename:
            logger.warning(f"Unknown sound ID {sound_id}")
            return

        wav_path = get_asset_path(filename)
        if not os.path.isfile(wav_path):
            logger.warning(f"Audio file not found: {wav_path}")
            return

        logger.info(f"Playing on Laptop speakers: {filename}")
        try:
            import winsound
            winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            logger.error(f"Error playing sound on laptop: {e}")

    def play_random_reprimand(self):
        """Pick a random mid-penalty motivational drill line."""
        snd = random.choice([SOUND_PUSH_PLANET, SOUND_HEAVY_BOOTS, SOUND_SLUG_SPRINT])
        self.play(snd)
