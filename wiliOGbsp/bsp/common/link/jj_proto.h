/* Application-level link messages for jumping jack telemetry between
 * Display CPU (where LIS3DH accelerometer and I2S speaker run) and Main CPU
 * (which routes to the Bottlenose Orca / ESP32 breakout).
 *
 * Types start at 0x30 to avoid collisions with bootloader (0x01-0x1F) and
 * IO expander direction control (0x20-0x2F). */
#ifndef FWOG_JJ_PROTO_H
#define FWOG_JJ_PROTO_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FWOG_JJ_MSG_TELEMETRY   0x30u  /* Display -> Main */
#define FWOG_JJ_MSG_SET_TARGET  0x31u  /* Main -> Display */
#define FWOG_JJ_MSG_PLAY_SOUND  0x32u  /* Main -> Display */

#define FWOG_JJ_SOUND_VOICE_SWIVEL   1u /* Ocular reconnaissance / swivel neck */
#define FWOG_JJ_SOUND_VOICE_PLANET   2u /* Push planet / push 'em out */
#define FWOG_JJ_SOUND_VOICE_BOOTS    3u /* Flutter kicks / heavy boots */
#define FWOG_JJ_SOUND_VOICE_SLUGS    4u /* Slugs sprint faster */
#define FWOG_JJ_SOUND_VOICE_CLEARED  5u /* Penalty cleared / dismissed */

/* Semantic aliases */
#define FWOG_JJ_SOUND_OFFICER_ALERT  FWOG_JJ_SOUND_VOICE_SWIVEL
#define FWOG_JJ_SOUND_REPRIMAND      FWOG_JJ_SOUND_VOICE_PLANET
#define FWOG_JJ_SOUND_VICTORY        FWOG_JJ_SOUND_VOICE_CLEARED

typedef struct __attribute__((packed)) {
    uint8_t  type;           /* FWOG_JJ_MSG_TELEMETRY (0x30) */
    uint8_t  seq;            /* Rolling message counter */
    uint16_t jump_count;     /* Completed jumping jacks */
    uint16_t target_count;   /* Target jumping jacks */
    uint8_t  state;          /* 0=IDLE, 1=DIP, 2=THRUST, 3=FLIGHT, 4=LANDED */
    uint16_t accel_mag_mg;   /* Smoothed total G magnitude in milli-g */
    uint16_t peak_g_mg;      /* Peak G of latest rep */
} fwog_jj_telemetry_msg_t;
_Static_assert(sizeof(fwog_jj_telemetry_msg_t) == 11,
               "fwog_jj_telemetry_msg_t goes on the wire unserialized");

typedef struct __attribute__((packed)) {
    uint8_t  type;           /* FWOG_JJ_MSG_SET_TARGET (0x31) */
    uint8_t  seq;
    uint16_t target;         /* New jumping jack target count */
    uint8_t  reset_count;    /* 1 = reset jump count to 0 */
} fwog_jj_set_target_msg_t;
_Static_assert(sizeof(fwog_jj_set_target_msg_t) == 5,
               "fwog_jj_set_target_msg_t goes on the wire unserialized");

typedef struct __attribute__((packed)) {
    uint8_t  type;           /* FWOG_JJ_MSG_PLAY_SOUND (0x32) */
    uint8_t  seq;
    uint8_t  sound_id;       /* FWOG_JJ_SOUND_* */
} fwog_jj_play_sound_msg_t;
_Static_assert(sizeof(fwog_jj_play_sound_msg_t) == 3,
               "fwog_jj_play_sound_msg_t goes on the wire unserialized");

#define FWOG_JJ_MSG_SET_VOLUME  0x33u  /* Main -> Display */

typedef struct __attribute__((packed)) {
    uint8_t  type;           /* FWOG_JJ_MSG_SET_VOLUME (0x33) */
    uint8_t  seq;
    uint8_t  volume_pct;     /* Volume percentage 0-100 */
} fwog_jj_set_volume_msg_t;
_Static_assert(sizeof(fwog_jj_set_volume_msg_t) == 3,
               "fwog_jj_set_volume_msg_t goes on the wire unserialized");

size_t fwog_jj_proto_build_telemetry(void *out, size_t cap, uint8_t seq,
                                     uint16_t count, uint16_t target,
                                     uint8_t state, uint16_t accel_mg, uint16_t peak_mg);

size_t fwog_jj_proto_build_set_target(void *out, size_t cap, uint8_t seq,
                                      uint16_t target, bool reset_count);

size_t fwog_jj_proto_build_play_sound(void *out, size_t cap, uint8_t seq,
                                      uint8_t sound_id);

size_t fwog_jj_proto_build_set_volume(void *out, size_t cap, uint8_t seq,
                                      uint8_t volume_pct);

uint8_t fwog_jj_proto_type(const void *payload, size_t len);

#endif
