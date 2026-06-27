/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#ifndef SMC_STRAP_H
#define SMC_STRAP_H

#include "smc_reg_access.h"

// SMC Strap bit positions (based on smc_utils.py)
typedef enum
{
  SMC_STRAP_SEP_BYPASS_MEM_REPAIR = 13,
  SMC_STRAP_SEP_TEST_EN = 14,
  SMC_STRAP_BOOT_STALL = 17,
  SMC_STRAP_BOOT_I2C = 18,
  SMC_STRAP_SEP_USE_FUSED_CONFIG = 22,
  SMC_STRAP_PRIMARY_CHIPLET = 25,
  SMC_STRAP_DISABLE_SMC_AUTO_ZERO = 26,
  SMC_STRAP_BOOT_RECOVERY = 19,
  SMC_STRAP_BL0_PLLCLK = 20,
  SMC_STRAP_STATUS_RPT_DISABLE = 21,
  SMC_STRAP_ROTATE_UPDATE = 61,
  SMC_STRAP_CHIP_ID_0 = 57,
  SMC_STRAP_CHIP_ID_1 = 55,
  SMC_STRAP_CHIP_ID_2 = 12,
  SMC_STRAP_CHIP_ID_3 = 11
} SmcStrapBit;

// Read strap value from GPIO_CTRL register's CONTROL field.
// Note: `strap_bit` selects which GPIO_CTRL register (GPIO index), not a bit position within the register.
static inline bool smc_strap_is_set(SmcStrapBit strap_bit)
{
  uint32_t reg_value;

  // Each GPIO_CTRL register is spaced 0x20 apart (GPIO_CTRL_1 - GPIO_CTRL_0 = 0xC0004460 - 0xC0004440)
  uint32_t gpio_ctrl_addr = SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(0) + (strap_bit * (SMC_TOP_GPIO_CTRL_BASE_ADDR(1) - SMC_TOP_GPIO_CTRL_BASE_ADDR(0)));

  reg_value = read_reg(gpio_ctrl_addr);

  // strap_valid/strap_value are hardware-written fields in GPIO_CTRL_x.CONTROL.
  // Use the generated mask definitions (do NOT use `strap_bit` as a bit index).
  return ((reg_value & GPIO_CTRL__CONTROL__STRAP_VALID_bm) != 0) &&
         ((reg_value & GPIO_CTRL__CONTROL__STRAP_VALUE_bm) != 0);
}

#endif /* SMC_STRAP_H */
