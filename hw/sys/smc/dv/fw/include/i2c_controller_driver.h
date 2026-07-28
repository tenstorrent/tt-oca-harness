/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Abstract I2C controller driver interface.
 *
 * Defines the I2C_Driver vtable and supporting types.  The default weak stub
 * returns NULL from I2C_GetDriverInstance(); platform drivers override it
 * with a strong symbol.
 */

#ifndef I2C_CONTROLLER_DRIVER_H_
#define I2C_CONTROLLER_DRIVER_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
    TARGET_I2C_SLAVE = 0,
    TARGET_I2C_MASTER = 1,
} target_i2c_mode_t;

typedef enum {
    I2C_OK = 0,
    I2C_TX_BUF_UNDERRUN = 1,
    I2C_RX_BUF_OVERFLOW = 2,
    I2C_TX_FIFO_FULL = 3,
    I2C_RX_FIFO_EMPTY = 4,
    I2C_ERR_HW = 5,
    I2C_TIMEOUT = 6,
} I2C_Status;

typedef struct I2C_Driver I2C_Driver;

void wait_for_i2c_target_ready(I2C_Driver *drv);

struct I2C_Driver {
    void (*release_reset)(uint8_t controller_id);
    I2C_Status (*init_i2c_ctrlr)(I2C_Driver *drv, uint8_t i2c_addr);
    I2C_Status (*ctrlr_send_data)(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len);
    I2C_Status (*ctrlr_send_data_w_timeout)(I2C_Driver *drv, const uint8_t *tx_buf,
                                            size_t tx_buf_len, int timeout);
    I2C_Status (*ctrlr_receive_data)(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                                     size_t *bytes_received);
    I2C_Status (*ctrlr_receive_data_w_timeout)(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                                               size_t *bytes_received, int timeout);
    struct {
        uint8_t controller_id;
        target_i2c_mode_t mode;
        bool initialized;
    } ctx;
};

/*
 * Obtain a driver instance for the given controller.
 *
 * Weak default (i2c_controller_driver.c) returns NULL; a real I2C
 * implementation overrides with a strong symbol.
 */
I2C_Driver *I2C_GetDriverInstance(uint8_t controller_id);
void I2C_release_reset(uint8_t controller_id);
I2C_Status init_i2c_ctrlr(I2C_Driver *drv, uint8_t i2c_addr);
I2C_Status ctrlr_send_data(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len);
I2C_Status ctrlr_send_data_w_timeout(I2C_Driver *drv, const uint8_t *tx_buf, size_t tx_buf_len,
                                     int timeout);
I2C_Status ctrlr_receive_data(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                              size_t *bytes_received);
I2C_Status ctrlr_receive_data_w_timeout(I2C_Driver *drv, uint8_t *rx_buf, size_t rx_buf_len,
                                        size_t *bytes_received, int timeout);

#endif /* I2C_CONTROLLER_DRIVER_H_ */
