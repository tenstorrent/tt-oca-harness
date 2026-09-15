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
    /* I2C/I3C ID configuration. Each fuse element is 64 bits wide: a static ID occupies bits
     * 6:0, a provisional ID the full width.
     */
    uint64_t i3c_id_0;          /* I2C/I3C ID slot 0 */
    uint64_t i3c_id_1;          /* I2C/I3C ID slot 1 */
    uint64_t i3c_id_3;          /* I2C/I3C ID slot 3 */
    uint64_t i2c_id_0;          /* I2C ID slot 6 */
    uint64_t i2c_id_1;          /* I2C ID slot 7 */
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
const smc_efuse_config_t *smc_efuse_get_config(void);

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
