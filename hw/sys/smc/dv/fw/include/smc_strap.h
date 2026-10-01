/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_STRAP_H
#define SMC_STRAP_H

#include "smc_addr.h"
#include "smc_reg_access.h"

// SMC strap GPIO indices, ordered by index.
typedef enum {
    SMC_STRAP_CHIP_ID_3 = 11,
    SMC_STRAP_CHIP_ID_2 = 12,
    SMC_STRAP_MEM_REPAIR_BYPASS = 13,
    SMC_STRAP_TEST_EN = 14,
    SMC_STRAP_CHIP_ID_1 = 15,
    SMC_STRAP_BOOT_I2C = 18,
    SMC_STRAP_BOOT_RECOVERY = 19,
    SMC_STRAP_BL0_PLLCLK = 20,
    SMC_STRAP_STATUS_RPT_DISABLE = 21,
    SMC_STRAP_SPI_USE_FUSED_CONFIG = 22,
    SMC_STRAP_CHIP_ID_0 = 23,
    SMC_STRAP_PRIMARY_CHIPLET = 25,
    SMC_STRAP_SRAM_AUTO_ZERO_DISABLE = 26,
    SMC_STRAP_MEM_BIST_BYPASS = 54,
    SMC_STRAP_ROTATE_UPDATE = 58
} SmcStrapBit;

// Captured straps, presented to firmware as two read-only words: bit N of STRAPS_LO is
// GPIO N, and STRAPS_HI continues at GPIO 32.
//
// Not smc_top_regs.h's SMC_RESET_UNIT_STRAPS_LO (0xC0002090). That register moved out of
// the reset unit into the external supplementary region and no longer exists; the generated
// header still carries the old macro.
#define SMC_STRAPS_LO_REG_ADDR SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_STRAPS_STRAPS_LO_BASE_ADDR
#define SMC_STRAPS_HI_REG_ADDR SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_STRAPS_STRAPS_HI_BASE_ADDR
#define SMC_STRAPS_LO_BIT_COUNT 32

// Reads the strap latched on one GPIO. `strap_bit` is the GPIO index.
static inline bool smc_strap_is_set(SmcStrapBit strap_bit) {
    bool in_lo = strap_bit < SMC_STRAPS_LO_BIT_COUNT;
    uint32_t addr = in_lo ? SMC_STRAPS_LO_REG_ADDR : SMC_STRAPS_HI_REG_ADDR;
    uint32_t bit = in_lo ? (uint32_t)strap_bit : (uint32_t)strap_bit - SMC_STRAPS_LO_BIT_COUNT;

    return (read_reg(addr) & (1u << bit)) != 0;
}

#endif /* SMC_STRAP_H */
