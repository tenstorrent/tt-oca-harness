/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Default weak stub for the I2C controller driver.
 *
 * All OCCP DV tests run in I3C mode (+BOOT_I3C); the I2C path in
 * occp_interfaces.c is never executed in simulation.  This stub satisfies
 * the link-time symbol requirements.
 *
 * I2C_GetDriverInstance is declared __attribute__((weak)) so a real I2C
 * implementation can override it at link time with a strong symbol.
 */

#include "i2c_controller_driver.h"
#include "virt_console.h"

__attribute__((weak))
I2C_Driver *I2C_GetDriverInstance(uint8_t controller_id)
{
    (void)controller_id;
    simputs("[i2c_stub] I2C not available in this build\n");
    return NULL;
}

void I2C_release_reset(uint8_t controller_id)
{
    (void)controller_id;
}

I2C_Status init_i2c_ctrlr(I2C_Driver *drv, uint8_t i2c_addr)
{
    (void)drv;
    (void)i2c_addr;
    return I2C_ERR_HW;
}

I2C_Status ctrlr_send_data(I2C_Driver *drv, const uint8_t *tx_buf,
                            size_t tx_buf_len)
{
    (void)drv; (void)tx_buf; (void)tx_buf_len;
    return I2C_ERR_HW;
}

I2C_Status ctrlr_send_data_w_timeout(I2C_Driver *drv, const uint8_t *tx_buf,
                                      size_t tx_buf_len, int timeout)
{
    (void)drv; (void)tx_buf; (void)tx_buf_len; (void)timeout;
    return I2C_ERR_HW;
}

I2C_Status ctrlr_receive_data(I2C_Driver *drv, uint8_t *rx_buf,
                               size_t rx_buf_len, size_t *bytes_received)
{
    (void)drv; (void)rx_buf; (void)rx_buf_len; (void)bytes_received;
    return I2C_ERR_HW;
}

I2C_Status ctrlr_receive_data_w_timeout(I2C_Driver *drv, uint8_t *rx_buf,
                                         size_t rx_buf_len,
                                         size_t *bytes_received, int timeout)
{
    (void)drv; (void)rx_buf; (void)rx_buf_len;
    (void)bytes_received; (void)timeout;
    return I2C_ERR_HW;
}

void wait_for_i2c_target_ready(I2C_Driver *drv)
{
    (void)drv;
}
