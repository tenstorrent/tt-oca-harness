/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Efuse Driver Implementation
 * Efuse access for I2C/I3C addressing and boot configuration.
 */

#include "smc_efuse.h"
#include "smc_defines.h"

/* Global efuse configuration structure */
static smc_efuse_config_t g_smc_efuse = {0};

/* Internal initialization flag */
static uint8_t g_efuse_initialized = 0;

/* Initialize the efuse driver and read essential fuse data */
int smc_efuse_init(void) {
    /* Clear the configuration structure */
    g_smc_efuse = (smc_efuse_config_t){0};

    g_smc_efuse.i3c_id_0 = read64_reg(SMC_EFUSE_MAP_I2C_I3C_ID_0__REG_ADDR);
    g_smc_efuse.i3c_id_1 = read64_reg(SMC_EFUSE_MAP_I2C_I3C_ID_1__REG_ADDR);
    g_smc_efuse.i3c_id_3 = read64_reg(SMC_EFUSE_MAP_I2C_I3C_ID_3__REG_ADDR);
    g_smc_efuse.i2c_id_0 = read64_reg(SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR);
    g_smc_efuse.i2c_id_1 = read64_reg(SMC_EFUSE_MAP_I2C_I3C_ID_7__REG_ADDR);

    /* Timeout occupies the low word of OCCP_TRANSPORT_TIMEOUT; the high word is reserved. */
    g_smc_efuse.transport_timeout =
        (uint32_t)read64_reg(SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_REG_ADDR);

    /* Mark as initialized */
    g_efuse_initialized = 1;

    return 0;
}

/**
 * Get the efuse configuration structure
 */
const smc_efuse_config_t *smc_efuse_get_config(void) {
    if (!g_efuse_initialized) {
        return NULL;
    }
    return &g_smc_efuse;
}

/**
 * Get I2C/I3C ID configuration
 */
uint64_t smc_efuse_get_i2c_i3c_id(uint8_t slot_id) {
    switch (slot_id) {
    case 0:
        return g_smc_efuse.i3c_id_0;
    case 1:
        return g_smc_efuse.i3c_id_1;
    case 2:
        return 0;
    case 3:
        return g_smc_efuse.i3c_id_3;
    case 4:
        return 0;
    case 5:
        return 0;
    case 6:
        return g_smc_efuse.i2c_id_0;
    case 7:
        return g_smc_efuse.i2c_id_1;
    case 8:
        return 0;

    default:
        return 0;
    }
}

uint32_t smc_efuse_get_transport_timeout(void) {
    return g_smc_efuse.transport_timeout;
}
