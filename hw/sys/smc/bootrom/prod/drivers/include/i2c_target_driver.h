/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef I2C_TARGET_DRIVER_I2C_DRIVER_H_
#define I2C_TARGET_DRIVER_I2C_DRIVER_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/**
 * Public interface identical to `firmware/prod_rom/drivers/include/i2c.h`.
 * This allows the experimental driver to be dropped in without touching users.
 */

typedef enum {
    TARGET_I2C_STOP_DISABLE = 0,
    TARGET_I2C_STOP_ENABLE = 1,
} target_i2c_stop_bit_t;

typedef enum {
    TARGET_I2C_SLAVE = 0,
    TARGET_I2C_MASTER = 1,
} target_i2c_mode_t;

typedef enum {
    I2C_OK = 0,
    I2C_ERR_HW = 1,
    I2C_ERR_OVERFLOW = 2,
    I2C_ERR_INCOMPLETE = 3,
    I2C_ERR_TIMEOUT = 4,
    I2C_ERR_TX_BUF_UNDERRUN = 5,
} I2C_Status;

typedef struct I2C_Driver I2C_Driver;

struct I2C_Driver {
    void (*release_reset)(uint8_t i2c_id);
    I2C_Status (*init_target)(I2C_Driver *drv, uint8_t i2c_addr);
    I2C_Status (*read_target)(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len,
                              uint32_t timeout);
    I2C_Status (*write_target)(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                               size_t *bytes_received, uint32_t timeout, bool expect_start_det,
                               bool expect_stop_det);
    uint32_t (*check_rx_fifo)(I2C_Driver *drv);

    struct {
        uint8_t controller_id;
        target_i2c_mode_t mode;
        bool initialized;
    } ctx;
};

I2C_Driver *I2C_GetDriverInstance(uint8_t i2c_id);
void I2C_release_reset(uint8_t i2c_id);
I2C_Status init_target(I2C_Driver *drv, uint8_t i2c_addr);
I2C_Status read_target(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len, uint32_t timeout);
I2C_Status write_target(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len, size_t *bytes_received,
                        uint32_t timeout, bool expect_start_det, bool expect_stop_det);
uint32_t check_rx_fifo(I2C_Driver *drv);

#endif //
