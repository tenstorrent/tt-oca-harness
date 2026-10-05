/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Strap Driver Implementation
 * Hardware strap configuration access.
 */

#include "smc_strap.h"
#include "smc_defines.h"
#include "smc_rom_defs.h"
#include "smc_post_code.h"
#include "smc_status.h"
#include "smc_occp_error_codes.h"

static inline uint8_t make_chip_id(void);
static inline void smc_strap_post_code_update(void);

/* Global strap configuration structure */
static smc_strap_config_t g_smc_straps = {0};

/* Internal flag to track initialization */
static uint8_t g_strap_initialized = 0;

/* Initialize the SMC strap configuration */
void smc_strap_init(void) {
    /* Read raw strap register values */
    g_smc_straps.straps_lo_raw = read_reg(SMC_STRAPS_LO_REG_ADDR);
    g_smc_straps.straps_hi_raw = read_reg(SMC_STRAPS_HI_REG_ADDR);

    /* Parse individual strap bits from LO register */
    g_smc_straps.sram_auto_zero_disable =
        (g_smc_straps.straps_lo_raw & SMC_STRAP_SRAM_AUTO_ZERO_DISABLE_MASK) ? 1 : 0;

    g_smc_straps.status_rpt_disable =
        (g_smc_straps.straps_lo_raw & SMC_STRAP_STATUS_RPT_DISABLE_MASK) ? 1 : 0;

    g_smc_straps.bl0_pllclk = (g_smc_straps.straps_lo_raw & SMC_STRAP_BL0_PLLCLK_MASK) ? 1 : 0;

    // Extract chip ID from both LO and HI registers
    g_smc_straps.chip_id = make_chip_id();

    g_smc_straps.bypass_sram_repair =
        (g_smc_straps.straps_lo_raw & SMC_STRAP_MEM_REPAIR_BYPASS_MASK) ? 1 : 0;

    g_smc_straps.test_en = (g_smc_straps.straps_lo_raw & SMC_STRAP_TEST_EN_MASK) ? 1 : 0;

    g_smc_straps.spi_use_fused_config =
        (g_smc_straps.straps_lo_raw & SMC_STRAP_SPI_USE_FUSED_CONFIG_MASK) ? 1 : 0;

    g_smc_straps.primary_chiplet =
        (g_smc_straps.straps_lo_raw & SMC_STRAP_PRIMARY_CHIPLET_MASK) ? 1 : 0;

    g_smc_straps.boot_i2c = (g_smc_straps.straps_lo_raw & SMC_STRAP_BOOT_I2C_MASK) ? 1 : 0;

    g_smc_straps.boot_recovery =
        (g_smc_straps.straps_lo_raw & SMC_STRAP_BOOT_RECOVERY_MASK) ? 1 : 0;

    g_smc_straps.rotate_update =
        (g_smc_straps.straps_hi_raw & SMC_STRAP_ROTATE_UPDATE_MASK) ? 1 : 0;

    /* Mark as initialized */
    g_strap_initialized = 1;

    smc_strap_post_code_update();
}

/**
 * Get the global strap configuration structure
 */
inline const smc_strap_config_t *smc_strap_get_config(void) {
    return &g_smc_straps;
}

/**
 * Check if SRAM auto-zero is disabled by strap
 */
inline uint8_t smc_strap_is_sram_auto_zero_disabled(void) {
    return g_smc_straps.sram_auto_zero_disable;
}

/**
 * Returns the value of the chip ID [3:0] bits from straps.
 *
 * @return Chip ID [3:0]
 */
uint8_t smc_strap_get_chip_id(void) {
    return g_smc_straps.chip_id;
}

/**
 * Check if OCCP status reporting is disabled
 */
inline uint8_t smc_strap_is_status_rpt_disable(void) {
    return g_smc_straps.status_rpt_disable;
}

/**
 * Get raw strap LO register value
 */
inline uint32_t smc_strap_get_raw_lo(void) {
    return g_smc_straps.straps_lo_raw;
}

/**
 * Check if BL0_PLLCLK strap is set (PLL configuration enabled)
 */
inline uint8_t smc_strap_is_bl0_pllclk_enabled(void) {
    return g_smc_straps.bl0_pllclk;
}

/**
 * Get raw strap HI register value
 */
inline uint32_t smc_strap_get_raw_hi(void) {
    return g_smc_straps.straps_hi_raw;
}

static inline uint8_t make_chip_id(void) {
    uint8_t chip_id = 0;
    // All CHIP_ID straps now live in STRAPS_LO (CHIP_ID_3=11, _2=12, _1=15, _0=23).
    chip_id |= (g_smc_straps.straps_lo_raw & SMC_STRAP_CHIP_ID_3_MASK) ? 1 << 3 : 0;
    chip_id |= (g_smc_straps.straps_lo_raw & SMC_STRAP_CHIP_ID_2_MASK) ? 1 << 2 : 0;
    chip_id |= (g_smc_straps.straps_lo_raw & SMC_STRAP_CHIP_ID_1_MASK) ? 1 << 1 : 0;
    chip_id |= (g_smc_straps.straps_lo_raw & SMC_STRAP_CHIP_ID_0_MASK) ? 1 : 0;

    return chip_id;
}

static inline void smc_strap_post_code_update(void) {
    uint8_t strap_status_bits = 0;

    /* Update POST code based on SRAM auto-zero disable strap */
    if (g_smc_straps.sram_auto_zero_disable) {
        smc_post_code_mark_sram_auto_zero_disabled();
    } else {
        smc_post_code_clear_sram_auto_zero_disabled();
    }

    /* Update POST code based on primary chiplet strap */
    if (g_smc_straps.primary_chiplet) {
        smc_post_code_mark_primary();
        /* Report boot modes detected */
        smc_status_report(SMC_STATUS_TYPE_STATUS,
                          SMC_STATUS_PRIMARY_MODE); // report primary mode or secondary mode though
                                                    // it doesn't affect the SMC ROM behavior
    } else {
        smc_post_code_mark_secondary();
        smc_status_report(
            SMC_STATUS_TYPE_STATUS,
            SMC_STATUS_SECONDARY_MODE); // report primary mode or secondary mode though it doesn't
                                        // affect the SMC ROM behavior
    }

    /* Update POST code based on boot recovery strap */
    if (g_smc_straps.boot_recovery) {
        smc_status_report(SMC_STATUS_TYPE_WARNING,
                          SMC_STATUS_RECOVERY_MODE); // report boot recovery mode
        smc_post_code_mark_recovery_mode();
    }

    /* Update POST code based on boot I2C strap */
    if (g_smc_straps.boot_i2c) {
        smc_post_code_mark_i2c_boot();
    }

    /* Update POST code strap status bits */
    if (g_smc_straps.status_rpt_disable) {
        strap_status_bits |=
            (uint8_t)(1U << (POST_CODE_STRAP_STATUS_RPT_DIS_BIT - POST_CODE_STRAP_STATUS_SHIFT));
    }
    if (g_smc_straps.bypass_sram_repair) {
        strap_status_bits |=
            (uint8_t)(1U << (POST_CODE_STRAP_SRAM_REPAIR_BYP_BIT - POST_CODE_STRAP_STATUS_SHIFT));
    }

    smc_post_code_set_strap_status(strap_status_bits);
}
