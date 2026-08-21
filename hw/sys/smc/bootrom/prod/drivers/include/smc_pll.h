/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC PLL Driver
 * Clock generation and PLL configuration for SMC ROM.
 * Provides PLL initialization and clock switching for auxiliary chiplets.
 */

#ifndef SMC_PLL_H
#define SMC_PLL_H

#include <stdint.h>
#include <stdbool.h>

/**
 * PLL initialization result codes
 */
typedef enum {
    SMC_PLL_SUCCESS = 0,
    SMC_PLL_ERROR_CONFIG_FAILED,
    SMC_PLL_ERROR_LOCK_TIMEOUT
} smc_pll_result_t;

/**
 * Initialize PLL configuration.
 *
 * The default implementation is a weak no-op hook. Platform-specific ROM
 * builds can override this symbol to implement PLL/refclk setup.
 *
 * @return SMC_PLL_SUCCESS if successful, appropriate error code otherwise
 */
smc_pll_result_t smc_pll_init(void);

/**
 * Check if PLL initialization is required for this chiplet
 *
 * @return true if PLL init is needed (auxiliary chiplet + BL0_PLLCLK strap), false otherwise
 */
// bool smc_pll_init_required(void);

/**
 * Get chiplet type (for clock configuration purposes)
 *
 * @return Chiplet ID from RESET_UNIT_CHIP_ID register
 */
uint8_t smc_pll_get_chiplet_type(void);

/**
 * Convert PLL result code to string for debugging
 *
 * @param result PLL result code
 * @return String representation of the result code
 */
const char *smc_pll_result_to_string(smc_pll_result_t result);

#endif /* SMC_PLL_H */
