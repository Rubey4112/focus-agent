#!/usr/bin/env python3
"""Build drill sergeant vocal audio clips for FreeWili OG.

Generates 8000 Hz, 8-bit mono PCM audio for authentic military drill sergeant
voice lines and exports them as a C translation unit with static sample arrays.
"""

import os
import subprocess
import wave
import struct

VOICE_SCRIPTS = [
    (
        "VOICE_SWIVEL_NECK",
        "Did somebody tell you to swivel your neck, private? Did I issue an order authorizing ocular reconnaissance? No! Then why are your eyeballs wandering around my drill deck looking for a parking spot? Put that phone down and jump!",
    ),
    (
        "VOICE_PUSH_PLANET",
        "You think this is funny? You think my grass needs fertilizing with your sweat? You are pushing that planet away from you, and I am not impressed by the velocity! Why are your arms shaking? Is gravity offending you today? Move!",
    ),
    (
        "VOICE_HEAVY_BOOTS",
        "One, two, three, one! Are your boots too heavy for you, warrior? Do you need me to carry them for you? Don't you dare drop those heels! If those boots touch my dirt before I say so, we are staying out here until the sun forgets where it lives! Move those legs!",
    ),
    (
        "VOICE_SLUG_MOTIVATION",
        "I have seen slugs move faster than this! Quitting is not an option on my watch! Pump those legs! Jump higher, soldier!",
    ),
    (
        "VOICE_PENALTY_CLEARED",
        "Target completed! Penalty cleared, private! Get off my drill deck, pick up your work, and focus! Dismissed!",
    ),
]

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT_DIR, "wiliOGbsp", "apps", "focus_agent", "display")
SCRATCH_DIR = os.path.join(ROOT_DIR, "scratch_audio")


def main():
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    clips = []

    for idx, (sym, text) in enumerate(VOICE_SCRIPTS):
        wav_path = os.path.join(SCRATCH_DIR, f"{sym.lower()}.wav")
        safe_text = text.replace('"', '\\"')

        ps_script = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = 100
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("{wav_path}", $f)
$s.Rate = 2
$s.Speak("{safe_text}")
$s.Dispose()
"""
        ps_file = os.path.join(SCRATCH_DIR, f"gen_{idx}.ps1")
        with open(ps_file, "w", encoding="utf-8") as f:
            f.write(ps_script)

        print(f"Generating voice clip {idx+1}/{len(VOICE_SCRIPTS)}: {sym}...")
        res = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_file], capture_output=True)
        if res.returncode != 0:
            print("Error generating speech:", res.stderr.decode())
            return

        # Read back raw PCM bytes from WAV
        with wave.open(wav_path, "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            pcm_bytes = wf.readframes(nframes)

        # Normalize 8-bit unsigned PCM samples around 128 to maximize dynamic range
        samples = [b - 128 for b in pcm_bytes]
        max_abs = max(abs(s) for s in samples) if samples else 1
        if max_abs > 0:
            scale = 127.0 / max_abs
            norm_bytes = bytes([min(255, max(0, int(128 + round(s * scale)))) for s in samples])
        else:
            norm_bytes = pcm_bytes

        print(f"  -> {len(norm_bytes)} PCM samples (rate={framerate}Hz, width={sampwidth}B, ch={nchannels}, peak_scale={scale:.2f})")
        clips.append((sym, text, norm_bytes))

    # Generate C header
    h_path = os.path.join(OUT_DIR, "drill_sergeant_audio.h")
    with open(h_path, "w", encoding="utf-8") as f:
        f.write("/* Auto-generated drill sergeant vocal audio clips for FreeWili OG I2S speaker */\n")
        f.write("#ifndef DRILL_SERGEANT_AUDIO_H\n")
        f.write("#define DRILL_SERGEANT_AUDIO_H\n")
        f.write("#include <stdint.h>\n")
        f.write("#include <stddef.h>\n\n")

        for idx, (sym, text, _) in enumerate(clips):
            f.write(f"#define {sym}_ID {idx + 1}u\n")
        f.write(f"#define DRILL_VOICE_COUNT {len(clips)}u\n\n")

        f.write("typedef struct {\n")
        f.write("    const char *name;\n")
        f.write("    const uint8_t *samples;\n")
        f.write("    unsigned count;\n")
        f.write("} drill_voice_clip_t;\n\n")

        f.write("extern const drill_voice_clip_t g_drill_voices[DRILL_VOICE_COUNT];\n\n")
        f.write("const drill_voice_clip_t *drill_voice_get(uint8_t sound_id);\n\n")
        f.write("#endif\n")

    # Generate C implementation
    c_path = os.path.join(OUT_DIR, "drill_sergeant_audio.c")
    with open(c_path, "w", encoding="utf-8") as f:
        f.write('#include "drill_sergeant_audio.h"\n\n')

        for sym, text, pcm_bytes in clips:
            f.write(f"/* {sym}: \"{text}\" */\n")
            f.write(f"static const uint8_t s_pcm_{sym.lower()}[{len(pcm_bytes)}] = {{\n")
            for i in range(0, len(pcm_bytes), 16):
                chunk = pcm_bytes[i : i + 16]
                line = ", ".join(f"0x{b:02x}" for b in chunk)
                f.write(f"    {line},\n")
            f.write("};\n\n")

        f.write("const drill_voice_clip_t g_drill_voices[DRILL_VOICE_COUNT] = {\n")
        for sym, _, pcm_bytes in clips:
            f.write(f'    {{ "{sym}", s_pcm_{sym.lower()}, {len(pcm_bytes)}u }},\n')
        f.write("};\n\n")

        f.write("const drill_voice_clip_t *drill_voice_get(uint8_t sound_id) {\n")
        f.write("    if (sound_id >= 1u && sound_id <= DRILL_VOICE_COUNT) {\n")
        f.write("        return &g_drill_voices[sound_id - 1u];\n")
        f.write("    }\n")
        f.write("    return &g_drill_voices[0];\n")
        f.write("}\n")

    print(f"\n[SUCCESS] Generated {h_path} and {c_path}!")


if __name__ == "__main__":
    main()
