/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Efuse Driver Implementation
 * Efuse access for device identity and configuration.
 */

#include "smc_efuse.h"
#include "smc_defines.h"
#include "smc_rom_defs.h"
#include "smc_top_regs.h" /* For efuse register definitions */

/* Global efuse configuration structure */
static smc_efuse_config_t g_smc_efuse = {0};

/* Internal initialization flag */
static uint8_t g_efuse_initialized = 0;

/* Initialize the efuse driver and read essential fuse data */
int smc_efuse_init(void)
{
    uint32_t chiplet_id_reg[8] = {0}; /* 256-bit register = 8 x 32-bit words */
    uint32_t sop_topology_reg = 0;
    int i;

    /* Clear the configuration structure */
    g_smc_efuse = (smc_efuse_config_t){0};

    /* Read CHIPLET_ID (256-bit register, but we only need the first 32 bits) */
    for (i = 0; i < 8; i++)
    {
        chiplet_id_reg[i] = read_reg(SMC_EFUSE_MAP_CHIPLET_ID_REG_ADDR + (i * 4));
    }
    /* We only care about the low 32 bits for I3C addressing */
    g_smc_efuse.chiplet_id = chiplet_id_reg[0];

    /* Read SOP_TOPOLOGY serial number */
    sop_topology_reg = read_reg(SMC_EFUSE_MAP_SOP_TOPOLOGY_REG_ADDR);
    g_smc_efuse.serial_number = sop_topology_reg;

    /* Read I2C/I3C ID configuration */
    // need two separate reads since it is not 64 bit aligned
    g_smc_efuse.i3c_id_0 = read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_0__REG_ADDR) | ((uint64_t)(read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_0__REG_ADDR + 4)) << 32);
    g_smc_efuse.i3c_id_1 = read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_1__REG_ADDR) | ((uint64_t)(read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_1__REG_ADDR + 4)) << 32);
    g_smc_efuse.i3c_id_3 = read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_3__REG_ADDR) | ((uint64_t)(read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_3__REG_ADDR + 4)) << 32);
    g_smc_efuse.i2c_id_0 = read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR) | ((uint64_t)(read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_6__REG_ADDR + 4)) << 32);
    g_smc_efuse.i2c_id_1 = read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_7__REG_ADDR) | ((uint64_t)(read_reg(SMC_EFUSE_MAP_I2C_I3C_ID_7__REG_ADDR + 4)) << 32);

    g_smc_efuse.transport_timeout = read_reg(SMC_EFUSE_MAP_RESERVED_1__REG_ADDR); // 32 bit register

    /* Mark as initialized */
    g_efuse_initialized = 1;

    return 0;
}

/**
 * Get the efuse configuration structure
 */
const smc_efuse_config_t *smc_efuse_get_config(void)
{
    if (!g_efuse_initialized)
    {
        return NULL;
    }
    return &g_smc_efuse;
}

/**
 * Get the chiplet ID from efuse
 */
uint32_t smc_efuse_get_chiplet_id(void)
{
    return g_smc_efuse.chiplet_id;
}

/**
 * Get the I3C device address from chiplet ID efuse
 */
uint8_t smc_efuse_get_i3c_address(void)
{
    /* I3C device address is the low 7 bits of chiplet ID */
    return (uint8_t)(g_smc_efuse.chiplet_id & 0x7F);
}

/**
 * Get the serial number from SOP topology efuse
 */
uint32_t smc_efuse_get_serial_number(void)
{
    return g_smc_efuse.serial_number;
}

/**
 * Get I2C/I3C ID configuration
 */
uint64_t smc_efuse_get_i2c_i3c_id(uint8_t slot_id)
{
    switch (slot_id)
    {
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

uint32_t smc_efuse_get_transport_timeout(void)
{
    return g_smc_efuse.transport_timeout;
}