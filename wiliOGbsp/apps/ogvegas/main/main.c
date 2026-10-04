#include "fwog_main.h"
#include "pico/stdlib.h"

FWOG_WATCHDOG_DEFAULT();

int main(void) {
    board_init();
    const fwog_display_result_t display = fwog_display_update_run();

    while (true) {
        board_watchdog_kick();
        DIAG("[ogvegas_main] display: %s\n", fwog_display_result_text(display));
        sleep_ms(1000);
    }
}
