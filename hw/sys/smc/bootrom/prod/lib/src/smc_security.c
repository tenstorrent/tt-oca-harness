/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Security Utilities Implementation
 * Device lifecycle and security mode detection.
 */

#include "smc_security.h"
#include "smc_defines.h"

/* Get the current lifecycle (LC) state from hardware */
uint8_t smc_security_get_lc_state(void)
{
    return (uint8_t)(read_reg(SMC_LC_STATE_REG_ADDR) & SMC_LC_STATE_MASK);
}

/**
 * Check if the device is in secure mode (PROD or PROD_END)
 * Note: PROD_DBG uses same encoding as PROD but is treated as unsecure
 */
uint8_t smc_security_is_secure_mode(void)
{
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_SECURE(lc_state) ? 1 : 0;
}

/**
 * Check if the device is in production mode specifically
 */
uint8_t smc_security_is_production_mode(void)
{
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_PROD(lc_state) ? 1 : 0;
}

/**
 * Check if the device is in RMA SOP mode
 */
uint8_t smc_security_is_rma_sop_mode(void)
{
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_RMA_SOP(lc_state) ? 1 : 0;
}

/**
 * Check if device security is in invalid state
 */
uint8_t smc_security_is_invalid_mode(void)
{
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_INVALID(lc_state) ? 1 : 0;
}