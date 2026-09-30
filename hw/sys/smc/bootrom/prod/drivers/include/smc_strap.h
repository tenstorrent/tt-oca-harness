/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Strap Driver
 * Hardware strap configuration access.
 */

#ifndef SMC_STRAP_H
#define SMC_STRAP_H

#include <stdint.h>

/* SMC Strap Configuration Structure
 * Holds all parsed strap values for easy access throughout the ROM code.
 * Initialize once at boot and use throughout the firmware.
 */
typedef struct {
    /* Raw strap register values */
    uint32_t straps_lo_raw;
    uint32_t straps_hi_raw;

    /* Parsed strap flags (boolean values) */
    uint8_t bypass_sram_repair;     /* 1 = Bypass the memory repair process */
    uint8_t test_en;                /* 1 = Enable DFT test mode */
    uint8_t spi_use_fused_config;   /* 1 = Use SPI configuration values stored in fuse field */
    uint8_t sram_auto_zero_disable; /* 1 = SRAM auto-zero is disabled */
    uint8_t primary_chiplet;        /* 1 = This is the primary chiplet (boot master) */
    uint8_t boot_i2c;               /* 1 = Boot from I2C (default is I3C0) */
    uint8_t boot_recovery;          /* 1 = Use I3C0 for BL1 boot image loading instead of SPI */
    uint8_t bl0_pllclk;             /* 1 = Use reference clock (default is PLL generated clock) */
    uint8_t rotate_update;          /* 1 = Swaps primary and backup image in SEP BL0 ROM */
    uint8_t status_rpt_disable;     /* 1 = Disable BL0 status reporting */
    uint8_t chip_id;                /* Chip ID bits [3:0] - I2C/I3C static address strap */

    /* Additional parsed fields can be added here as needed */
    uint8_t _reserved[1]; /* Padding for future expansion */
} smc_strap_config_t;

/**
 * Initialize the SMC strap configuration
 * This function reads the hardware strap registers and parses them into
 * the global strap configuration structure for easy access throughout the ROM.
 *
 *
 * @note This function should be called once early in the boot process
 */
void smc_strap_init(void);

/**
 * Get the global strap configuration structure
 *
 *
 * @return Pointer to the global strap configuration
 */
const smc_strap_config_t *smc_strap_get_config(void);

/**
 * Check if SRAM auto-zero is disabled by strap
 *
 *
 * @return 1 if SRAM auto-zero is disabled, 0 otherwise
 */
uint8_t smc_strap_is_sram_auto_zero_disabled(void);

/**
 * Returns the value of the chip ID [3:0] bits from straps.
 *
 * @return Chip ID [3:0]
 */
uint8_t smc_strap_get_chip_id(void);

/**
 * Check if OCCP status reporting is disabled
 *
 * @return 1 if status reporting is disabled, 0 otherwise
 */
uint8_t smc_strap_is_status_rpt_disable(void);

/**
 * Check if BL0_PLLCLK strap is set (PLL configuration enabled)
 *
 * @return 1 if BL0_PLLCLK strap is set, 0 otherwise
 */
uint8_t smc_strap_is_bl0_pllclk_enabled(void);

/**
 * Get raw strap LO register value
 *
 * @return Raw strap LO register value
 */
uint32_t smc_strap_get_raw_lo(void);

/**
 * Get raw strap LO register value
 *
 *
 * @return Raw strap LO register value
 */
uint32_t smc_strap_get_raw_lo(void);

/**
 * Get raw strap HI register value
 *
 *
 * @return Raw strap HI register value
 */
uint32_t smc_strap_get_raw_hi(void);

#endif /* SMC_STRAP_H */
