/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Interface Map Driver
 * Interface availability mapping based on device operating mode.
 */

#ifndef SMC_INTERFACE_MAP_H
#define SMC_INTERFACE_MAP_H

#include <stdint.h>

/* Interface availability map structure
 * Indicates which communication interfaces are enabled based on device mode
 */
typedef struct {
    uint8_t i2c0_enabled; /* 1 = I2C interface 0 is enabled */
    uint8_t i2c1_enabled; /* 1 = I2C interface 1 is enabled */
    uint8_t i3c0_enabled; /* 1 = I3C interface 0 is enabled */
    uint8_t i3c1_enabled; /* 1 = I3C interface 1 is enabled */
    uint8_t i3c2_enabled; /* 1 = I3C interface 2 is enabled */
    uint8_t i3c3_enabled; /* 1 = I3C interface 3 is enabled */
    // TODO: Add 13C 4
    uint8_t _reserved[3]; /* Padding for future expansion */
} smc_interface_map_t;

/**
 * Initialize the interface map based on current device operating mode
 *
 * Current implementation enables all supported interfaces uniformly:
 * - I2C0: Enabled (all chiplets)
 * - I2C1: Enabled (all chiplets)
 * - I3C0: Enabled (all chiplets)
 * - I3C1: Enabled (all chiplets)
 * - I3C2: Reserved/disabled
 * - I3C3: Enabled (all chiplets)
 *
 * Note: Interface configuration differentiation based on PRIMARY_CHIPLET
 * strap and other boot mode controls will be implemented to support the
 * full chiplet coordination model in BL#1 and beyond (per prod_rom spec).
 */
int smc_interface_map_init(void);

/* Get the current interface map */
const smc_interface_map_t *smc_interface_map_get(void);

/**
 * Get a bitmask of all enabled interfaces
 * @return Bitmask where bit 0=I2C0, bit 1=I3C0, bit 2=I3C1, bit 3=I3C2, bit 4=I3C3
 */
uint8_t smc_interface_map_get_enabled_mask(void);

/**
 * Check if interface map has been initialized
 * @return 1 if initialized, 0 otherwise
 */
uint8_t smc_interface_map_is_initialized(void);

/**
 * Check if any I3C interface is enabled
 * @return 1 if any I3C interface is enabled, 0 otherwise
 */
uint8_t smc_interface_map_has_i3c_enabled(void);

#endif /* SMC_INTERFACE_MAP_H */
