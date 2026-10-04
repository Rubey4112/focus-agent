/* Auto-generated drill sergeant vocal audio clips for FreeWili OG I2S speaker */
#ifndef DRILL_SERGEANT_AUDIO_H
#define DRILL_SERGEANT_AUDIO_H
#include <stdint.h>
#include <stddef.h>

#define VOICE_SWIVEL_NECK_ID 1u
#define VOICE_PUSH_PLANET_ID 2u
#define VOICE_HEAVY_BOOTS_ID 3u
#define VOICE_SLUG_MOTIVATION_ID 4u
#define VOICE_PENALTY_CLEARED_ID 5u
#define DRILL_VOICE_COUNT 5u

typedef struct {
    const char *name;
    const uint8_t *samples;
    unsigned count;
} drill_voice_clip_t;

extern const drill_voice_clip_t g_drill_voices[DRILL_VOICE_COUNT];

const drill_voice_clip_t *drill_voice_get(uint8_t sound_id);

#endif
