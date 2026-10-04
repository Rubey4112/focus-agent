#include "common/link/jj_proto.h"
#include <string.h>

size_t fwog_jj_proto_build_telemetry(void *out, size_t cap, uint8_t seq,
                                     uint16_t count, uint16_t target,
                                     uint8_t state, uint16_t accel_mg, uint16_t peak_mg) {
    if (cap < sizeof(fwog_jj_telemetry_msg_t)) return 0;
    fwog_jj_telemetry_msg_t *m = (fwog_jj_telemetry_msg_t *)out;
    m->type = FWOG_JJ_MSG_TELEMETRY;
    m->seq = seq;
    m->jump_count = count;
    m->target_count = target;
    m->state = state;
    m->accel_mag_mg = accel_mg;
    m->peak_g_mg = peak_mg;
    return sizeof(fwog_jj_telemetry_msg_t);
}

size_t fwog_jj_proto_build_set_target(void *out, size_t cap, uint8_t seq,
                                      uint16_t target, bool reset_count) {
    if (cap < sizeof(fwog_jj_set_target_msg_t)) return 0;
    fwog_jj_set_target_msg_t *m = (fwog_jj_set_target_msg_t *)out;
    m->type = FWOG_JJ_MSG_SET_TARGET;
    m->seq = seq;
    m->target = target;
    m->reset_count = reset_count ? 1u : 0u;
    return sizeof(fwog_jj_set_target_msg_t);
}

size_t fwog_jj_proto_build_play_sound(void *out, size_t cap, uint8_t seq,
                                      uint8_t sound_id) {
    if (cap < sizeof(fwog_jj_play_sound_msg_t)) return 0;
    fwog_jj_play_sound_msg_t *m = (fwog_jj_play_sound_msg_t *)out;
    m->type = FWOG_JJ_MSG_PLAY_SOUND;
    m->seq = seq;
    m->sound_id = sound_id;
    return sizeof(fwog_jj_play_sound_msg_t);
}

size_t fwog_jj_proto_build_set_volume(void *out, size_t cap, uint8_t seq,
                                      uint8_t volume_pct) {
    if (cap < sizeof(fwog_jj_set_volume_msg_t)) return 0;
    fwog_jj_set_volume_msg_t *m = (fwog_jj_set_volume_msg_t *)out;
    m->type = FWOG_JJ_MSG_SET_VOLUME;
    m->seq = seq;
    m->volume_pct = (volume_pct > 100u) ? 100u : volume_pct;
    return sizeof(fwog_jj_set_volume_msg_t);
}

uint8_t fwog_jj_proto_type(const void *payload, size_t len) {
    if (len == 0 || payload == NULL) return 0;
    const uint8_t *p = (const uint8_t *)payload;
    if (p[0] == FWOG_JJ_MSG_TELEMETRY && len >= sizeof(fwog_jj_telemetry_msg_t)) return FWOG_JJ_MSG_TELEMETRY;
    if (p[0] == FWOG_JJ_MSG_SET_TARGET && len >= sizeof(fwog_jj_set_target_msg_t)) return FWOG_JJ_MSG_SET_TARGET;
    if (p[0] == FWOG_JJ_MSG_PLAY_SOUND && len >= sizeof(fwog_jj_play_sound_msg_t)) return FWOG_JJ_MSG_PLAY_SOUND;
    if (p[0] == FWOG_JJ_MSG_SET_VOLUME && len >= sizeof(fwog_jj_set_volume_msg_t)) return FWOG_JJ_MSG_SET_VOLUME;
    return 0;
}
