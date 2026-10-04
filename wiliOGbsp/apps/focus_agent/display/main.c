#include "fwog_display.h"
#include "pico/stdlib.h"
#include "common/link/jj_proto.h"
#include "common/link/link_uart.h"
#include "common/link/link_frame.h"
#include "audio/i2s_audio.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Red held 6 s powers the board off, with the LED countdown on the WS2812 bar. */
FWOG_POWER_DEFAULT();

static uint8_t s_jj_seq = 0;
static void send_telemetry(uint16_t count, uint16_t target, uint8_t state, uint16_t accel_mg, uint16_t peak_mg) {
    uint8_t payload[sizeof(fwog_jj_telemetry_msg_t)];
    size_t n = fwog_jj_proto_build_telemetry(payload, sizeof(payload), s_jj_seq++,
                                             count, target, state, accel_mg, peak_mg);
    if (n) {
        (void)fwog_link_uart_send_frame(payload, n);
    }
}

#include "drill_sergeant_audio.h"

static float s_voice_gain = 4.8f; /* Boost 8-bit audio across full 16-bit DAC dynamic range (+13.6 dB) */

static void play_alert_sound(uint8_t sound_id) {
    const drill_voice_clip_t *clip = drill_voice_get(sound_id);
    if (clip && clip->samples && clip->count > 0) {
        DIAG("[focus_agent] Playing vocal speech: %s (%u samples, gain=%.1f)\n",
             clip->name, clip->count, (double)s_voice_gain);
        i2s_audio_stop();
        i2s_audio_set_volume(10);
        i2s_audio_set_asset_gain(s_voice_gain);
        i2s_audio_start(clip->samples, clip->count, true, true);
    }
}

/* ---- Minimalist House Arrest Tether Palette (RGB565) ---- */
#define COL_BG_BLACK    st7789_rgb565(8, 8, 10)         /* Pure Void Charcoal */
#define COL_PANEL       st7789_rgb565(16, 18, 22)       /* Frosted Charcoal Card */
#define COL_BORDER      st7789_rgb565(36, 40, 48)       /* Subtle Frosted Zinc Border */
#define COL_TRACK       st7789_rgb565(24, 26, 32)       /* Solid Dark Track */
#define COL_WHITE       0xFFFFu                         /* Crisp Stark White */
#define COL_MUTED       st7789_rgb565(120, 125, 138)    /* Tactical Silver */
#define COL_CRIMSON     st7789_rgb565(250, 45, 60)      /* Enforcement Alert Crimson */
#define COL_EMERALD     st7789_rgb565(16, 185, 129)     /* Restored Emerald */

/* ---- Jumping Jack Detection Engine ---- */
typedef enum {
    JJ_STATE_IDLE = 0,
    JJ_STATE_DIP,
    JJ_STATE_THRUST,
    JJ_STATE_FLIGHT,
    JJ_STATE_LANDED
} jj_state_t;

typedef enum {
    SENS_NORMAL = 0,
    SENS_HIGH,
    SENS_LOW,
    SENS_COUNT
} jj_sens_t;

typedef struct {
    const char *name;
    uint32_t thrust_mg;     /* Upward propulsion threshold (milli-g) */
    uint32_t flight_mg;     /* Airborne / free-fall dip threshold */
    uint32_t landing_mg;    /* Ground contact impact threshold */
    uint32_t min_flight_ms; /* Minimum flight duration for true jump */
    uint32_t max_flight_ms; /* Maximum flight duration */
} jj_thresholds_t;

static const jj_thresholds_t s_thresholds[SENS_COUNT] = {
    [SENS_NORMAL] = {
        .name = "NORM",
        .thrust_mg = 1450,
        .flight_mg = 780,
        .landing_mg = 1520,
        .min_flight_ms = 60,
        .max_flight_ms = 580,
    },
    [SENS_HIGH] = {
        .name = "HIGH",
        .thrust_mg = 1650,
        .flight_mg = 680,
        .landing_mg = 1750,
        .min_flight_ms = 70,
        .max_flight_ms = 550,
    },
    [SENS_LOW] = {
        .name = "SENS",
        .thrust_mg = 1250,
        .flight_mg = 860,
        .landing_mg = 1320,
        .min_flight_ms = 40,
        .max_flight_ms = 650,
    },
};

/* Fast integer square root */
static inline uint32_t isqrt(uint32_t val) {
    uint32_t res = 0;
    uint32_t bit = 1u << 30;
    while (bit > val) bit >>= 2;
    while (bit != 0) {
        if (val >= res + bit) {
            val -= res + bit;
            res = (res >> 1) + bit;
        } else {
            res >>= 1;
        }
        bit >>= 2;
    }
    return res;
}

/* Minimalist House Arrest Tether UI drawn once at boot */
static void draw_static_ui(void) {
    /* Pure Void Charcoal Canvas */
    st7789_fill_rect(0, 0, ST7789_W, ST7789_H, COL_BG_BLACK);
    st7789_dma_wait();

    /* Header Bar (y: 0 to 28) */
    st7789_fill_rect(0, 0, ST7789_W, 28, COL_BG_BLACK);
    st7789_fill_rect(0, 28, ST7789_W, 1, COL_BORDER);
    lcd_text_draw(12, 10, "FOCUS AGENT // TETHER", 1, COL_WHITE, COL_BG_BLACK);
    lcd_text_draw(228, 10, "[LOCKED]", 1, COL_CRIMSON, COL_BG_BLACK);

    /* Centerpiece Discipline Card (y: 34 to 176, w: 304, h: 142) */
    st7789_fill_rect(8, 34, 304, 142, COL_PANEL);
    st7789_fill_rect(8, 34, 304, 1, COL_BORDER);
    st7789_fill_rect(8, 175, 304, 1, COL_BORDER);
    st7789_fill_rect(8, 34, 1, 142, COL_BORDER);
    st7789_fill_rect(311, 34, 1, 142, COL_BORDER);

    lcd_text_draw(84, 44, "JUMPING JACK COUNT", 1, COL_MUTED, COL_PANEL);

    /* Bottom Restraint Status Frame (y: 184 to 238) */
    st7789_fill_rect(0, 184, ST7789_W, 1, COL_BORDER);
    lcd_text_draw(12, 222, "TETHER STATUS: TAMPER CONTROLS LOCKED", 1, COL_MUTED, COL_BG_BLACK);
}

int main(void) {
    board_init();

    /* Bring up ST7789 320x240 LCD */
    st7789_init_begin();
    const absolute_time_t lcd_deadline = make_timeout_time_ms(1000);
    while (!st7789_ready() && !time_reached(lcd_deadline)) {
        st7789_init_step();
    }
    if (st7789_ready()) {
        board_backlight(255);
        draw_static_ui();
    }

    /* Initialize WS2812 7-LED bar */
    const bool ws_ok = ws2812_init(pio0, 0u);

    /* Initialize LIS3DH accelerometer (±4g range) */
    lis3dh_init();
    const bool accel_ok = lis3dh_configure(LIS3DH_RANGE_4G);

    /* Initialize inter-CPU link for telemetry forwarding */
    const bool link_ok = fwog_link_uart_init(FWOG_LINK_BAUD);

    /* Initialize MAX98357A I2S speaker driver on PIO0 SM1 */
    const bool audio_ok = i2s_audio_init(pio0, 1u);
    if (audio_ok) {
        i2s_audio_set_volume(10);
    }

    DIAG("[focus_agent] hardware init: lcd=%s ws2812=%s lis3dh=%s link=%s audio=%s\n",
         st7789_ready() ? "ok" : "fail", ws_ok ? "ok" : "fail", accel_ok ? "ok" : "fail",
         link_ok ? "ok" : "fail", audio_ok ? "ok" : "fail");

    /* Application State */
    uint32_t count = 0;
    uint32_t target = 20;
    jj_sens_t sens = SENS_NORMAL;
    jj_state_t state = JJ_STATE_IDLE;

    uint32_t state_enter_ms = 0;
    uint32_t thrust_time_ms = 0;
    uint32_t flight_time_ms = 0;
    uint32_t r_smooth_mg = 1000;
    uint32_t current_r_mg = 1000;
    uint32_t peak_mag_mg = 1000;
    uint32_t last_jump_peak_mg = 0;
    uint32_t flash_until_ms = 0;

    /* Cached display values to minimize redraw */
    int32_t last_disp_count = -1;
    int32_t last_disp_target = -1;
    int32_t last_disp_sens = -1;
    int32_t last_disp_state = -1;
    uint32_t last_disp_r = 0;
    uint32_t last_disp_prog_w = 999;
    uint32_t last_disp_bar_w = 999;

    absolute_time_t next_ui_update = make_timeout_time_ms(30);
    absolute_time_t next_diag_heartbeat = make_timeout_time_ms(2000);
    absolute_time_t next_telemetry_time = make_timeout_time_ms(100);

    while (true) {
        const uint32_t now_ms = to_ms_since_boot(get_absolute_time());

        /* 1. Poll power button & front panel buttons */
        fwog_power_t p = fwog_power_poll(now_ms);

        /* Button controls: All tamper actions (reset count, edit goal) are DISABLED.
         * House arrest bracelet enforcement is controlled exclusively by the host agent. */
        if (p.buttons.pressed & (FWOG_BTN_BIT(FWOG_BTN_GREEN) | FWOG_BTN_BIT(FWOG_BTN_BLUE) |
                                 FWOG_BTN_BIT(FWOG_BTN_YELLOW) | FWOG_BTN_BIT(FWOG_BTN_GRAY))) {
            DIAG("[focus_agent] Tamper button press blocked: device is locked\n");
            flash_until_ms = now_ms + 180;
        }

        /* 2. Sample Accelerometer (100 Hz ODR)
         * lis3dh_process() leaves out_sample untouched if no new data has arrived
         * (ZYXDA bit not set). Using 0x7FFF sentinel detects fresh hardware samples. */
        lis3dh_sample_t samp;
        samp.x = 0x7FFF;
        const bool proc_ok = lis3dh_process(LIS3DH_MOVE_THRESHOLD_DEFAULT, &samp, NULL);

        if (proc_ok && samp.x != 0x7FFF) {
            const int32_t mgx = lis3dh_raw_to_mg(samp.x, LIS3DH_RANGE_4G);
            const int32_t mgy = lis3dh_raw_to_mg(samp.y, LIS3DH_RANGE_4G);
            const int32_t mgz = lis3dh_raw_to_mg(samp.z, LIS3DH_RANGE_4G);

            const uint32_t sum_sq = (uint32_t)(mgx * mgx + mgy * mgy + mgz * mgz);
            current_r_mg = isqrt(sum_sq);

            /* Exponential moving average filter */
            r_smooth_mg = (r_smooth_mg * 3 + current_r_mg) / 4;

            if (current_r_mg > peak_mag_mg) {
                peak_mag_mg = current_r_mg;
            }

            /* 3. Jump Detection Finite State Machine */
            const jj_thresholds_t *th = &s_thresholds[sens];

            switch (state) {
            case JJ_STATE_IDLE:
                /* Upward propulsion / thrust trigger */
                if (current_r_mg >= th->thrust_mg) {
                    state = JJ_STATE_THRUST;
                    thrust_time_ms = now_ms;
                    state_enter_ms = now_ms;
                    peak_mag_mg = current_r_mg;
                } else if (current_r_mg <= th->flight_mg) {
                    /* Pre-jump crouch / dip */
                    state = JJ_STATE_DIP;
                    state_enter_ms = now_ms;
                }
                break;

            case JJ_STATE_DIP:
                /* From dip, spring upward into thrust */
                if (current_r_mg >= th->thrust_mg) {
                    state = JJ_STATE_THRUST;
                    thrust_time_ms = now_ms;
                    state_enter_ms = now_ms;
                    peak_mag_mg = current_r_mg;
                } else if ((now_ms - state_enter_ms) > 300) {
                    state = JJ_STATE_IDLE;
                }
                break;

            case JJ_STATE_THRUST:
                /* In flight / weightless phase */
                if (current_r_mg <= th->flight_mg) {
                    state = JJ_STATE_FLIGHT;
                    flight_time_ms = now_ms;
                    state_enter_ms = now_ms;
                } else if ((now_ms - thrust_time_ms) > 280) {
                    state = JJ_STATE_IDLE;
                }
                break;

            case JJ_STATE_FLIGHT:
                /* Landing impact */
                if (current_r_mg >= th->landing_mg) {
                    const uint32_t flight_dur = now_ms - flight_time_ms;
                    if (flight_dur >= th->min_flight_ms && flight_dur <= th->max_flight_ms) {
                        /* VALID JUMPING JACK COMPLETED! */
                        count++;
                        state = JJ_STATE_LANDED;
                        state_enter_ms = now_ms;
                        last_jump_peak_mg = (current_r_mg > peak_mag_mg) ? current_r_mg : peak_mag_mg;
                        flash_until_ms = now_ms + 300;

                        DIAG("[focus_agent] JUMP DETECTED! Count: %u, Peak: %u mg, Flight: %u ms\n",
                             (unsigned)count, (unsigned)last_jump_peak_mg, (unsigned)flight_dur);
                        send_telemetry((uint16_t)count, (uint16_t)target, (uint8_t)state, (uint16_t)r_smooth_mg, (uint16_t)last_jump_peak_mg);
                        if (count == target) {
                            play_alert_sound(FWOG_JJ_SOUND_VICTORY);
                        }
                    } else {
                        state = JJ_STATE_IDLE;
                    }
                } else if ((now_ms - flight_time_ms) > th->max_flight_ms) {
                    state = JJ_STATE_IDLE;
                }
                break;

            case JJ_STATE_LANDED:
                /* Refractory debounce period (350 ms) to prevent landing rebounds */
                if ((now_ms - state_enter_ms) > 350) {
                    state = JJ_STATE_IDLE;
                    peak_mag_mg = current_r_mg;
                }
                break;
            }
        }

        /* 4. Update WS2812 LEDs - Minimalist Tactical House Arrest Mode */
        if (ws_ok && !p.armed) {
            if (now_ms < flash_until_ms) {
                /* Flash crisp stark white on detected jump */
                for (unsigned i = 0; i < FWOG_LED_COUNT; i++) {
                    ws2812_set_color(i, 255, 255, 255);
                }
            } else if (count >= target) {
                /* Target reached: solid discipline emerald */
                for (unsigned i = 0; i < FWOG_LED_COUNT; i++) {
                    ws2812_set_color(i, 0, 255, 80);
                }
            } else {
                /* Clean stark white progress bar */
                const unsigned lit_leds = (target > 0) ? ((count % target) * FWOG_LED_COUNT / target) : 0;
                for (unsigned i = 0; i < FWOG_LED_COUNT; i++) {
                    if (i < lit_leds) {
                        ws2812_set_color(i, 160, 160, 180);   /* Crisp White */
                    } else if (i == lit_leds) {
                        ws2812_set_color(i, 40, 40, 50);      /* Dim Lead */
                    } else {
                        ws2812_set_color(i, 0, 0, 0);         /* Blackout */
                    }
                }
            }
            ws2812_process();
        }

        /* 5. Render Dynamic LCD UI (~30 FPS) */
        if (st7789_ready() && time_reached(next_ui_update)) {
            next_ui_update = make_timeout_time_ms(33);

            /* Giant Centerpiece Rep Counter (Scale 6) */
            if ((int32_t)count != last_disp_count || (now_ms < flash_until_ms)) {
                last_disp_count = (int32_t)count;

                char count_buf[8];
                snprintf(count_buf, sizeof(count_buf), "%4u", (unsigned)count);

                uint16_t num_col = COL_WHITE;
                if (now_ms < flash_until_ms) {
                    num_col = COL_CRIMSON;
                } else if (count >= target) {
                    num_col = COL_EMERALD;
                }

                /* Scale 6: 4 chars * 36px = 144px width. Centered at x = 88, y = 60. Height = 48px */
                lcd_text_draw_padded(88, 60, count_buf, 4, 6, num_col, COL_PANEL);

                /* Target Reps Requirement below giant number */
                char tgt_buf[32];
                if (count >= target) {
                    snprintf(tgt_buf, sizeof(tgt_buf), "GOAL SECURED: %u / %u REPS", (unsigned)count, (unsigned)target);
                    lcd_text_draw_padded(64, 116, tgt_buf, 26, 1, COL_EMERALD, COL_PANEL);
                } else {
                    snprintf(tgt_buf, sizeof(tgt_buf), "REQUIRED: %u REPETITIONS", (unsigned)target);
                    lcd_text_draw_padded(82, 116, tgt_buf, 24, 1, COL_MUTED, COL_PANEL);
                }
            }

            /* Minimalist High-Contrast Progress Bar (width: 272 px) */
            uint32_t prog_w = (target > 0) ? ((count > target ? target : count) * 272 / target) : 0;
            if (prog_w != last_disp_prog_w) {
                last_disp_prog_w = prog_w;
                uint16_t fill_col = (count >= target) ? COL_EMERALD : COL_WHITE;
                if (prog_w > 0) {
                    st7789_fill_rect(24, 134, (uint16_t)prog_w, 8, fill_col);
                }
                if (prog_w < 272) {
                    st7789_fill_rect(24 + (uint16_t)prog_w, 134, (uint16_t)(272 - prog_w), 8, COL_TRACK);
                }
                st7789_fill_rect(24, 133, 272, 1, COL_BORDER);
            }

            /* Jump State & Kinetic Motion Indicator inside centerpiece card */
            if ((int32_t)state != last_disp_state) {
                last_disp_state = (int32_t)state;
                const char *state_names[] = {
                    "STANDBY",
                    "DIP",
                    "THRUST",
                    "AIRBORNE",
                    "JUMP +1"
                };
                char st_buf[32];
                if (count >= target) {
                    snprintf(st_buf, sizeof(st_buf), "STATUS: [ ACCESS RESTORED ]");
                    lcd_text_draw_padded(64, 152, st_buf, 26, 1, COL_EMERALD, COL_PANEL);
                } else {
                    snprintf(st_buf, sizeof(st_buf), "MOTION: [ %-12s ]", state_names[state]);
                    lcd_text_draw_padded(76, 152, st_buf, 24, 1, (state == JJ_STATE_LANDED ? COL_WHITE : COL_MUTED), COL_PANEL);
                }
            }

            /* Lower Frame: Real-Time Acceleration Metrics */
            if (abs((int)r_smooth_mg - (int)last_disp_r) > 20 || now_ms < flash_until_ms) {
                last_disp_r = r_smooth_mg;

                char g_buf[40];
                const unsigned g_int = r_smooth_mg / 1000;
                const unsigned g_dec = (r_smooth_mg % 1000) / 10;
                const unsigned p_int = last_jump_peak_mg / 1000;
                const unsigned p_dec = (last_jump_peak_mg % 1000) / 10;

                snprintf(g_buf, sizeof(g_buf), "G-FORCE: %u.%02ug  |  PEAK: %u.%02ug",
                         g_int, g_dec, p_int, p_dec);
                lcd_text_draw_padded(36, 196, g_buf, 32, 1, COL_MUTED, COL_BG_BLACK);
            }
        }

        /* 6. Heartbeat output to host over USB CDC */
        if (time_reached(next_diag_heartbeat)) {
            next_diag_heartbeat = make_timeout_time_ms(3000);
            DIAG("[focus_agent] count=%u target=%u r=%u state=%d\n",
                 (unsigned)count, (unsigned)target, (unsigned)r_smooth_mg, state);
        }

        /* 7. Periodic telemetry over inter-CPU link (10 Hz) */
        if (time_reached(next_telemetry_time)) {
            next_telemetry_time = make_timeout_time_ms(100);
            send_telemetry((uint16_t)count, (uint16_t)target, (uint8_t)state,
                           (uint16_t)r_smooth_mg, (uint16_t)last_jump_peak_mg);
        }

        /* 8. Advance I2S speaker DMA playback */
        i2s_audio_process();

        /* 9. Process incoming commands from Main CPU (target sync, audio triggers) */
        static fwog_link_rx_t s_cmd_rx;
        uint8_t cmd_b;
        while (fwog_link_uart_read(&cmd_b)) {
            size_t n = 0;
            if (fwog_link_rx_byte(&s_cmd_rx, cmd_b, &n)) {
                uint8_t t = fwog_jj_proto_type(s_cmd_rx.buf, n);
                if (t == FWOG_JJ_MSG_SET_TARGET) {
                    const fwog_jj_set_target_msg_t *m = (const fwog_jj_set_target_msg_t *)s_cmd_rx.buf;
                    target = m->target;
                    if (m->reset_count) {
                        count = 0;
                        flash_until_ms = now_ms + 250;
                    }
                    DIAG("[focus_agent] TARGET SYNC FROM LAPTOP: %u (reset=%u)\n",
                         (unsigned)target, (unsigned)m->reset_count);
                    send_telemetry((uint16_t)count, (uint16_t)target, (uint8_t)state,
                                   (uint16_t)r_smooth_mg, (uint16_t)last_jump_peak_mg);
                } else if (t == FWOG_JJ_MSG_PLAY_SOUND) {
                    const fwog_jj_play_sound_msg_t *m = (const fwog_jj_play_sound_msg_t *)s_cmd_rx.buf;
                    DIAG("[focus_agent] PLAY SOUND COMMAND: %u\n", (unsigned)m->sound_id);
                    play_alert_sound(m->sound_id);
                } else if (t == FWOG_JJ_MSG_SET_VOLUME) {
                    const fwog_jj_set_volume_msg_t *m = (const fwog_jj_set_volume_msg_t *)s_cmd_rx.buf;
                    /* Scale 0-100% to 0.0 - 4.8f gain */
                    s_voice_gain = ((float)m->volume_pct / 100.0f) * 4.8f;
                    if (s_voice_gain < 0.05f) s_voice_gain = 0.0f;
                    DIAG("[focus_agent] VOLUME SYNC FROM LAPTOP: %u%% (gain=%.2f)\n",
                         (unsigned)m->volume_pct, (double)s_voice_gain);
                }
            }
        }

        sleep_ms(2);
    }
}
