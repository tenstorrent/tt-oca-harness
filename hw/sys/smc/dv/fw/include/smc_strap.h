/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_STRAP_H
#define SMC_STRAP_H

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

// Read strap value from GPIO_CTRL register's CONTROL field.
// Note: `strap_bit` selects which GPIO_CTRL register (GPIO index), not a bit position within the
// register.
static inline bool smc_strap_is_set(SmcStrapBit strap_bit) {
    uint32_t reg_value;

    // Each GPIO_CTRL register is spaced 0x20 apart (GPIO_CTRL_1 - GPIO_CTRL_0 = 0xC0401120 -
    // 0xC0401100)
    uint32_t gpio_ctrl_addr =
        SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(0) +
        (strap_bit * (SMC_TOP_GPIO_CTRL_BASE_ADDR(1) - SMC_TOP_GPIO_CTRL_BASE_ADDR(0)));

    reg_value = read_reg(gpio_ctrl_addr);

    // strap_valid/strap_value are hardware-written fields in GPIO_CTRL_x.CONTROL.
    // Use the generated mask definitions (do NOT use `strap_bit` as a bit index).
    return ((reg_value & GPIO_CTRL__CONTROL__STRAP_VALID_bm) != 0) &&
           ((reg_value & GPIO_CTRL__CONTROL__STRAP_VALUE_bm) != 0);
}

#endif /* SMC_STRAP_H */
