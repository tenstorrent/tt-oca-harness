/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Interface Map Driver Implementation
 * Interface availability mapping based on device operating mode.
 */

#include "smc_interface_map.h"
#include "smc_strap.h"
#include "smc_security.h"
#include "smc_rom_defs.h" /* For interface bit definitions */
#include <stddef.h>       /* For NULL definition */
#include <stdio.h>        /* For snprintf */
#include "virt_console.h" /* For simputs and simputshex16 */

/* Global interface map structure */
static smc_interface_map_t g_interface_map = {0};

/* Internal initialization flag */
static uint8_t g_interface_map_initialized = 0;
/**
 * Initialize the interface map based on current device operating mode
 */
int smc_interface_map_init(void) {

    /* Clear the interface map structure */
    g_interface_map = (smc_interface_map_t){0};

    /* I2C and I3C interfaces below are always enabled */
    g_interface_map.i2c0_enabled = 1;
    g_interface_map.i2c1_enabled = 1;
    g_interface_map.i3c0_enabled = 1;
    g_interface_map.i3c1_enabled = 1;
    /* I3C2: Reserved/disabled for now */
    g_interface_map.i3c2_enabled = 0;
    g_interface_map.i3c3_enabled = 1;

    /* Mark as initialized */
    g_interface_map_initialized = 1;

    return 0;
}

/**
 * Get the current interface map
 */
const smc_interface_map_t *smc_interface_map_get(void) {
    if (!g_interface_map_initialized) {
        return NULL;
    }
    return &g_interface_map;
}

/**
 * Check if interface map has been initialized
 */
uint8_t smc_interface_map_is_initialized(void) {
    return g_interface_map_initialized;
}

/**
 * Check if any I3C interface is enabled
 */
uint8_t smc_interface_map_has_i3c_enabled(void) {
    return (g_interface_map.i3c0_enabled || g_interface_map.i3c1_enabled ||
            g_interface_map.i3c2_enabled || g_interface_map.i3c3_enabled)
               ? 1
               : 0;
}
