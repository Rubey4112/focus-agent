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

/* ---- Display Palette (RGB565) ---- */
#define COL_BG          st7789_rgb565(12, 16, 26)       /* Deep Obsidian Navy */
#define COL_HDR_BG      st7789_rgb565(26, 32, 58)       /* Indigo Header */
#define COL_CYAN        st7789_rgb565(0, 230, 255)      /* Electric Cyan */
#define COL_CARD_BG     st7789_rgb565(20, 25, 40)       /* Card Slate */
#define COL_CARD_BORDER st7789_rgb565(42, 55, 88)       /* Subtle Border */
#define COL_MUTED       st7789_rgb565(130, 145, 175)    /* Muted Slate Text */
#define COL_WHITE       0xFFFFu                         /* Pure White */
#define COL_EMERALD     st7789_rgb565(0, 255, 130)      /* Neon Emerald */
#define COL_GOLD        st7789_rgb565(255, 210, 0)      /* Solar Gold */
#define COL_ORANGE      st7789_rgb565(255, 140, 0)      /* Vivid Orange */
#define COL_PURPLE      st7789_rgb565(190, 80, 255)     /* Flight Purple */
#define COL_RED         st7789_rgb565(255, 50, 60)      /* Coral Red */
#define COL_TRACK       st7789_rgb565(32, 38, 54)       /* Gauge Track */

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

/* UI Card Outline Helper */
static void draw_card(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t bg, uint16_t border) {
    st7789_fill_rect(x, y, w, h, bg);
    st7789_fill_rect(x, y, w, 1, border);
    st7789_fill_rect(x, y + h - 1, w, 1, border);
    st7789_fill_rect(x, y, 1, h, border);
    st7789_fill_rect(x + w - 1, y, 1, h, border);
}

/* Static UI Chrome drawn once at boot */
static void draw_static_ui(void) {
    st7789_clear(COL_BG);
    st7789_dma_wait();

    /* Header Banner */
    st7789_fill_rect(0, 0, ST7789_W, 30, COL_HDR_BG);
    st7789_fill_rect(0, 30, ST7789_W, 2, COL_CYAN);
    lcd_text_draw(12, 7, "FOCUS AGENT", 2, COL_CYAN, COL_HDR_BG);

    /* Main Counter Card */
    draw_card(10, 38, 300, 106, COL_CARD_BG, COL_CARD_BORDER);
    lcd_text_draw(20, 46, "JUMPING JACKS", 1, COL_MUTED, COL_CARD_BG);

    /* Accelerometer Status Card */
    draw_card(10, 150, 300, 54, COL_CARD_BG, COL_CARD_BORDER);

    /* Bottom Button Controls Guide */
    st7789_fill_rect(0, 210, ST7789_W, 1, COL_CARD_BORDER);
    lcd_text_draw(8, 220, "[GRN]", 1, COL_EMERALD, COL_BG);
    lcd_text_draw(40, 220, "Reset", 1, COL_MUTED, COL_BG);
    lcd_text_draw(88, 220, "[BLU]", 1, COL_CYAN, COL_BG);
    lcd_text_draw(120, 220, "+5", 1, COL_MUTED, COL_BG);
    lcd_text_draw(148, 220, "[YEL]", 1, COL_GOLD, COL_BG);
    lcd_text_draw(180, 220, "-5", 1, COL_MUTED, COL_BG);
    lcd_text_draw(208, 220, "[GRY]", 1, COL_PURPLE, COL_BG);
    lcd_text_draw(240, 220, "Sens", 1, COL_MUTED, COL_BG);
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

        /* Button controls */
        if (p.buttons.pressed & FWOG_BTN_BIT(FWOG_BTN_GREEN)) {
            count = 0;
            flash_until_ms = now_ms + 250;
            DIAG("[focus_agent] Counter reset to 0\n");
            send_telemetry((uint16_t)count, (uint16_t)target, (uint8_t)state, (uint16_t)r_smooth_mg, (uint16_t)last_jump_peak_mg);
        }
        if (p.buttons.pressed & FWOG_BTN_BIT(FWOG_BTN_BLUE)) {
            if (target < 100) target += 5;
            DIAG("[focus_agent] Target increased to %u\n", (unsigned)target);
            send_telemetry((uint16_t)count, (uint16_t)target, (uint8_t)state, (uint16_t)r_smooth_mg, (uint16_t)last_jump_peak_mg);
        }
        if (p.buttons.pressed & FWOG_BTN_BIT(FWOG_BTN_YELLOW)) {
            if (target > 5) target -= 5;
            DIAG("[focus_agent] Target decreased to %u\n", (unsigned)target);
            send_telemetry((uint16_t)count, (uint16_t)target, (uint8_t)state, (uint16_t)r_smooth_mg, (uint16_t)last_jump_peak_mg);
        }
        if (p.buttons.pressed & FWOG_BTN_BIT(FWOG_BTN_GRAY)) {
            sens = (sens + 1) % SENS_COUNT;
            DIAG("[focus_agent] Sensitivity changed to %s\n", s_thresholds[sens].name);
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

        /* 4. Update WS2812 LEDs */
        if (ws_ok && !p.armed) {
            if (now_ms < flash_until_ms) {
                /* Flash brilliant emerald on detected jump */
                for (unsigned i = 0; i < FWOG_LED_COUNT; i++) {
                    ws2812_set_color(i, 0, 255, 60);
                }
            } else if (count >= target) {
                /* Target reached: celebration rainbow wave */
                const uint32_t phase = (now_ms / 100) % 6;
                static const uint8_t rainbow[6][3] = {
                    {255, 0, 0}, {255, 120, 0}, {255, 220, 0},
                    {0, 255, 50}, {0, 180, 255}, {180, 0, 255}
                };
                for (unsigned i = 0; i < FWOG_LED_COUNT; i++) {
                    const unsigned ci = (phase + i) % 6;
                    ws2812_set_color(i, rainbow[ci][0], rainbow[ci][1], rainbow[ci][2]);
                }
            } else {
                /* Progress bar across 7 LEDs */
                const unsigned lit_leds = (target > 0) ? ((count % target) * FWOG_LED_COUNT / target) : 0;
                for (unsigned i = 0; i < FWOG_LED_COUNT; i++) {
                    if (i < lit_leds) {
                        ws2812_set_color(i, 0, 80, 200);   /* Vivid Cyan-Blue */
                    } else if (i == lit_leds) {
                        ws2812_set_color(i, 0, 25, 60);    /* Dim Lead */
                    } else {
                        ws2812_set_color(i, 1, 2, 6);      /* Ambient */
                    }
                }
            }
            ws2812_process();
        }

        /* 5. Render Dynamic LCD UI (~30 FPS) */
        if (st7789_ready() && time_reached(next_ui_update)) {
            next_ui_update = make_timeout_time_ms(33);

            /* Sensitivity Pill in Header */
            if ((int32_t)sens != last_disp_sens) {
                last_disp_sens = (int32_t)sens;
                char sens_str[16];
                snprintf(sens_str, sizeof(sens_str), "SENS: %-4s", s_thresholds[sens].name);
                lcd_text_draw_padded(216, 11, sens_str, 10, 1, COL_GOLD, COL_HDR_BG);
            }

            /* Target Label in Counter Card */
            if ((int32_t)target != last_disp_target) {
                last_disp_target = (int32_t)target;
                char tgt_str[16];
                snprintf(tgt_str, sizeof(tgt_str), "GOAL: %2u", (unsigned)target);
                lcd_text_draw_padded(230, 46, tgt_str, 8, 1, COL_GOLD, COL_CARD_BG);
            }

            /* Big Counter Number */
            if ((int32_t)count != last_disp_count || (now_ms < flash_until_ms)) {
                last_disp_count = (int32_t)count;

                char count_buf[8];
                snprintf(count_buf, sizeof(count_buf), "%4u", (unsigned)count);

                uint16_t num_col = COL_EMERALD;
                if (now_ms < flash_until_ms) {
                    num_col = COL_WHITE;
                } else if (count >= target) {
                    num_col = COL_GOLD;
                }
                /* Scale 4: 4 chars * 24px = 96px width. Centered at x=112, y=60 */
                lcd_text_draw_padded(112, 60, count_buf, 4, 4, num_col, COL_CARD_BG);

                /* Target reached banner inside card */
                if (count >= target) {
                    lcd_text_draw_padded(50, 96, "★ GOAL REACHED! ★", 17, 1, COL_GOLD, COL_CARD_BG);
                } else {
                    char prog_lbl[32];
                    const unsigned pct = (target > 0) ? (count * 100 / target) : 0;
                    snprintf(prog_lbl, sizeof(prog_lbl), "%u of %u (%u%%)",
                             (unsigned)count, (unsigned)target, pct);
                    lcd_text_draw_padded(50, 96, prog_lbl, 20, 1, COL_MUTED, COL_CARD_BG);
                }
            }

            /* Progress Bar (width: 276 px) */
            uint32_t prog_w = (target > 0) ? ((count > target ? target : count) * 276 / target) : 0;
            if (prog_w != last_disp_prog_w) {
                last_disp_prog_w = prog_w;
                const uint16_t fill_col = (count >= target) ? COL_GOLD : COL_CYAN;
                if (prog_w > 0) {
                    st7789_fill_rect(22, 114, (uint16_t)prog_w, 10, fill_col);
                }
                if (prog_w < 276) {
                    st7789_fill_rect(22 + (uint16_t)prog_w, 114, (uint16_t)(276 - prog_w), 10, COL_TRACK);
                }
            }

            /* Jump State Badge */
            if ((int32_t)state != last_disp_state) {
                last_disp_state = (int32_t)state;
                const char *state_names[] = {
                    "[ READY     ]",
                    "[ DIP       ]",
                    "[ THRUST >> ]",
                    "[ AIRBORNE! ]",
                    "[ JUMP +1!  ]"
                };
                const uint16_t state_cols[] = {
                    COL_CYAN,
                    COL_MUTED,
                    COL_ORANGE,
                    COL_PURPLE,
                    COL_EMERALD
                };
                lcd_text_draw_padded(20, 158, state_names[state], 13, 1, state_cols[state], COL_CARD_BG);
            }

            /* Acceleration Metrics */
            if (abs((int)r_smooth_mg - (int)last_disp_r) > 15 || now_ms < flash_until_ms) {
                last_disp_r = r_smooth_mg;

                char g_buf[32];
                const unsigned g_int = r_smooth_mg / 1000;
                const unsigned g_dec = (r_smooth_mg % 1000) / 10;
                const unsigned p_int = last_jump_peak_mg / 1000;
                const unsigned p_dec = (last_jump_peak_mg % 1000) / 10;

                snprintf(g_buf, sizeof(g_buf), "G:%u.%02ug  PK:%u.%02ug",
                         g_int, g_dec, p_int, p_dec);
                lcd_text_draw_padded(20, 172, g_buf, 20, 1, COL_WHITE, COL_CARD_BG);

                /* Mini Real-Time Acceleration Gauge (x: 180, y: 184, w: 120, h: 10) */
                /* Range: 0 to 3500 mg */
                uint32_t bar_w = (r_smooth_mg * 120) / 3500;
                if (bar_w > 120) bar_w = 120;

                if (bar_w != last_disp_bar_w) {
                    last_disp_bar_w = bar_w;
                    uint16_t bar_col = COL_CYAN;
                    if (r_smooth_mg < 800) {
                        bar_col = COL_PURPLE;      /* Weightless dip */
                    } else if (r_smooth_mg > 1800) {
                        bar_col = COL_RED;         /* High impact */
                    } else if (r_smooth_mg > 1400) {
                        bar_col = COL_ORANGE;      /* Push-off thrust */
                    }

                    if (bar_w > 0) {
                        st7789_fill_rect(180, 184, (uint16_t)bar_w, 10, bar_col);
                    }
                    if (bar_w < 120) {
                        st7789_fill_rect(180 + (uint16_t)bar_w, 184, (uint16_t)(120 - bar_w), 10, COL_TRACK);
                    }
                    /* Draw 1.0g reference tick mark at 1000/3500 * 120 = 34 px */
                    st7789_fill_rect(180 + 34, 182, 1, 14, COL_WHITE);
                }
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
