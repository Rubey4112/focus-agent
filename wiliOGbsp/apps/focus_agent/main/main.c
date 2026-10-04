#include "fwog_main.h"
#include "pico/stdlib.h"
#include "hardware/uart.h"
#include "hardware/gpio.h"
#include "common/link/jj_proto.h"
#include "common/link/link_uart.h"
#include "common/link/link_frame.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Every main app must kick the 8.3 s watchdog board_init() arms, and must
   declare that it does -- board_init() references the symbol this macro
   defines, so an app declaring neither policy does not link.
   See bsp/main_cpu/watchdog/watchdog.h. */
FWOG_WATCHDOG_DEFAULT();

#define BREAKOUT_UART_BAUD 115200u

int main(void) {
    board_init();

    /* Brings the display up: link, HELLO, reflash if the embedded image
       differs, then RUN. This performs board_release_display() itself. */
    fwog_display_result_t d = fwog_display_update_run();
    DIAG("[focus_agent_main] display: %s\n", fwog_display_result_text(d));

    /* Initialize Breakout UART1 for Bottlenose Orca / ESP32 communication.
       Pin 9 (GPIO 8) = UART1 TX, Pin 5 (GPIO 9) = UART1 RX */
    uart_init(uart1, BREAKOUT_UART_BAUD);
    gpio_set_function(PIN_IO_UART_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_IO_UART_RX, GPIO_FUNC_UART);
    uart_set_hw_flow(uart1, false, false);
    uart_set_format(uart1, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(uart1, true);

    DIAG("[focus_agent_main] breakout UART1 initialized at %u baud on GPIO %u (TX) / %u (RX)\n",
         (unsigned)BREAKOUT_UART_BAUD, (unsigned)PIN_IO_UART_TX, (unsigned)PIN_IO_UART_RX);

    /* Receiver state for the inter-CPU link (UART0) from Display CPU */
    static fwog_link_rx_t s_rx;
    fwog_link_rx_init(&s_rx);

    /* Buffer for incoming command lines from Breakout UART1 (ESP32/Laptop) */
    static char s_uart1_buf[128];
    static size_t s_uart1_pos = 0;
    static uint8_t s_cmd_seq = 0;

    absolute_time_t next_heartbeat = make_timeout_time_ms(3000);

    while (true) {
        board_watchdog_kick();      /* required: see watchdog.h */

        /* 1. Drain incoming packets from Display CPU across inter-CPU link */
        uint8_t b;
        while (fwog_link_uart_read(&b)) {
            size_t n = 0;
            if (fwog_link_rx_byte(&s_rx, b, &n)) {
                if (fwog_jj_proto_type(s_rx.buf, n) == FWOG_JJ_MSG_TELEMETRY) {
                    const fwog_jj_telemetry_msg_t *m = (const fwog_jj_telemetry_msg_t *)s_rx.buf;

                    /* Transmit JSON line to Bottlenose Orca / ESP32 over breakout UART1 */
                    char json[128];
                    int len = snprintf(json, sizeof(json),
                        "{\"jumps\":%u,\"target\":%u,\"state\":%u,\"g_mg\":%u,\"peak_mg\":%u}\n",
                        (unsigned)m->jump_count, (unsigned)m->target_count, (unsigned)m->state,
                        (unsigned)m->accel_mag_mg, (unsigned)m->peak_g_mg);
                    if (len > 0) {
                        uart_puts(uart1, json);
                    }

                    /* Also output to USB CDC DIAG for host debugging */
                    DIAG("[telemetry] jumps=%u target=%u state=%u g=%u peak=%u\n",
                         (unsigned)m->jump_count, (unsigned)m->target_count, (unsigned)m->state,
                         (unsigned)m->accel_mag_mg, (unsigned)m->peak_g_mg);
                }
            }
        }

        /* 2. Read incoming commands from Bottlenose Orca / Laptop across Breakout UART1 */
        while (uart_is_readable(uart1)) {
            char c = (char)uart_getc(uart1);
            if (c == '\n' || c == '\r') {
                if (s_uart1_pos > 0) {
                    s_uart1_buf[s_uart1_pos] = '\0';

                    /* Parse target configuration: e.g. {"cmd":"set_target","target":15} */
                    if (strstr(s_uart1_buf, "target") != NULL) {
                        char *p = strstr(s_uart1_buf, "target");
                        while (*p && (*p < '0' || *p > '9')) p++;
                        if (*p) {
                            int new_target = atoi(p);
                            if (new_target > 0) {
                                uint8_t frame[16];
                                size_t fn = fwog_jj_proto_build_set_target(
                                    frame, sizeof(frame), s_cmd_seq++, (uint16_t)new_target, true);
                                if (fn) {
                                    (void)fwog_link_uart_send_frame(frame, fn);
                                }
                                DIAG("[focus_agent_main] Synced target %d to Display CPU\n", new_target);
                            }
                        }
                    }

                    /* Parse sound trigger: e.g. {"cmd":"play_sound","sound":1} */
                    if (strstr(s_uart1_buf, "play") != NULL || strstr(s_uart1_buf, "sound") != NULL) {
                        char *p = strstr(s_uart1_buf, "sound");
                        if (!p) p = strstr(s_uart1_buf, "play");
                        while (*p && (*p < '0' || *p > '9')) p++;
                        int snd_id = *p ? atoi(p) : 1;
                        if (snd_id > 0) {
                            uint8_t frame[16];
                            size_t fn = fwog_jj_proto_build_play_sound(
                                frame, sizeof(frame), s_cmd_seq++, (uint8_t)snd_id);
                            if (fn) {
                                (void)fwog_link_uart_send_frame(frame, fn);
                            }
                            DIAG("[focus_agent_main] Sent sound trigger %d to Display CPU\n", snd_id);
                        }
                    }

                    /* Parse volume command: e.g. {"cmd":"set_volume","volume":100} */
                    if (strstr(s_uart1_buf, "volume") != NULL || strstr(s_uart1_buf, "vol") != NULL) {
                        char *p = strstr(s_uart1_buf, "volume");
                        if (!p) p = strstr(s_uart1_buf, "vol");
                        while (*p && (*p < '0' || *p > '9')) p++;
                        if (*p) {
                            int vol_pct = atoi(p);
                            if (vol_pct >= 0) {
                                uint8_t frame[16];
                                size_t fn = fwog_jj_proto_build_set_volume(
                                    frame, sizeof(frame), s_cmd_seq++, (uint8_t)vol_pct);
                                if (fn) {
                                    (void)fwog_link_uart_send_frame(frame, fn);
                                }
                                DIAG("[focus_agent_main] Sent volume %d%% to Display CPU\n", vol_pct);
                            }
                        }
                    }

                    s_uart1_pos = 0;
                }
            } else if (s_uart1_pos + 1 < sizeof(s_uart1_buf)) {
                s_uart1_buf[s_uart1_pos++] = c;
            }
        }

        if (time_reached(next_heartbeat)) {
            next_heartbeat = make_timeout_time_ms(3000);
            DIAG("[focus_agent_main] bridge active (UART1 <-> Orca/ESP32)\n");
        }

        sleep_ms(2);
    }
}
