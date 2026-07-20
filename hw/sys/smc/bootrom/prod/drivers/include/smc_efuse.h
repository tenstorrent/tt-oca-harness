/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Efuse Driver
 * Efuse access for device identity and configuration.
 */

#ifndef SMC_EFUSE_H
#define SMC_EFUSE_H

#include <stdint.h>

/* Efuse data structure for ROM operations
 * Contains only the essential fuses needed during ROM boot
 */
typedef struct {
    /* CHIPLET_ID fuse data (256-bit, but we only need the low 32 bits for I3C address) */
    uint32_t chiplet_id;        /* Low 7 bits used as I3C device address */

    /* SOP_TOPOLOGY serial number */
    uint32_t serial_number;     /* Package serial number */

    /* I2C/I3C ID configuration */
    uint32_t i3c_id_0;     /* I2C/I3C ID slot 0 */
    uint32_t i3c_id_1;     /* I2C/I3C ID slot 1 */
    uint32_t i3c_id_3;     /* I2C/I3C ID slot 3 */
    uint32_t i2c_id_0;     /* I2C ID slot 0 */
    uint32_t i2c_id_1;     /* I2C ID slot 0*/
    uint32_t transport_timeout; /* Transport timeout value from efuse */
} smc_efuse_config_t;

/**
 * Initialize the efuse driver and read essential fuse data
 * @return 0 on success, negative on error
 */
int smc_efuse_init(void);

/**
 * Get the efuse configuration structure
 * @return Pointer to efuse config structure (NULL if not initialized)
 */
const smc_efuse_config_t* smc_efuse_get_config(void);

/**
 * Get the chiplet ID from efuse (for I3C addressing)
 * @return Chiplet ID value, or 0 if not available
 */
uint32_t smc_efuse_get_chiplet_id(void);

/**
 * Get the I3C device address from chiplet ID efuse
 * @return 7-bit I3C device address (bits 6:0 of chiplet ID)
 */
uint8_t smc_efuse_get_i3c_address(void);

/**
 * Get the serial number from SOP topology efuse
 * @return Serial number, or 0 if not available
 */
uint32_t smc_efuse_get_serial_number(void);

/**
 * Get I2C/I3C ID configuration
 * @param slot_id Slot ID (0 or 1)
 * @return I2C/I3C ID value for the specified slot
 */
uint64_t smc_efuse_get_i2c_i3c_id(uint8_t slot_id);

/**
 * Get transport timeout value from efuse
 * @return Transport timeout in system clock cycles
 */
uint32_t smc_efuse_get_transport_timeout(void);

#endif /* SMC_EFUSE_H */
