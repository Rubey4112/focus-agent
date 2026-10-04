#include "common/i2c_bus.h"
#include "platform/board.h"
#include "hardware/i2c.h"
#include <string.h>

bool fwog_i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = { reg, val };
    int r = i2c_write_timeout_us(FWOG_I2C, addr, buf, 2, false,
                                 FWOG_I2C_TIMEOUT_US);
    return r == 2;
}

bool fwog_i2c_write_regs(uint8_t addr, uint8_t reg, const uint8_t *src, size_t n) {
    if (!src || n == 0u || n > FWOG_I2C_MAX_WRITE) return false;
    uint8_t buf[1u + FWOG_I2C_MAX_WRITE];
    buf[0] = reg;
    memcpy(&buf[1], src, n);
    int r = i2c_write_timeout_us(FWOG_I2C, addr, buf, n + 1u, false,
                                 FWOG_I2C_TIMEOUT_US);
    return r == (int)(n + 1u);
}

bool fwog_i2c_read_regs(uint8_t addr, uint8_t reg, uint8_t *dst, size_t n) {
    if (n == 0) return false;   /* see the header: not a successful read */
    int r = i2c_write_timeout_us(FWOG_I2C, addr, &reg, 1, true,
                                 FWOG_I2C_TIMEOUT_US);
    if (r != 1) return false;
    r = i2c_read_timeout_us(FWOG_I2C, addr, dst, n, false,
                            FWOG_I2C_TIMEOUT_US);
    return r == (int)n;
}

size_t fwog_i2c_scan(uint8_t *found, size_t cap) {
    size_t n = 0;
    for (uint8_t a = 0x08; a < 0x78 && n < cap; a++) {
        uint8_t dummy;
        if (i2c_read_timeout_us(FWOG_I2C, a, &dummy, 1, false,
                                FWOG_I2C_TIMEOUT_US) >= 0) {
            found[n++] = a;
        }
    }
    return n;
}
