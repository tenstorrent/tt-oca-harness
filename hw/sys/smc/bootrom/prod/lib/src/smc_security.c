/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Security Utilities Implementation
 * Device lifecycle and security mode detection.
 */

#include "smc_security.h"
#include "chip_config.h"
#include "smc_addr.h"
#include "smc_defines.h"

/* Read the raw 8-bit differentially encoded LC_STATE register value. */
static uint8_t smc_security_read_lc_state_raw(void) {
    return (uint8_t)(read_reg(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR) &
                     CHIP_CONFIG__LC_STATE__LC_STATE_bm);
}

/* Get the current lifecycle (LC) state from hardware */
uint8_t smc_security_get_lc_state(void) {
    uint8_t raw = smc_security_read_lc_state_raw();

    /* Fail closed: treat differential-encoding integrity errors as INVALID. */
    if (!SMC_LC_STATE_DIFF_IS_VALID(raw)) {
        return SMC_LC_STATE_INVALID;
    }

    return (uint8_t)(raw & SMC_LC_STATE_MASK);
}

/**
 * Check if the device is in secure mode (PROD or PROD_END)
 * Note: PROD_DBG uses same encoding as PROD but is treated as unsecure
 */
uint8_t smc_security_is_secure_mode(void) {
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_SECURE(lc_state) ? 1 : 0;
}

/**
 * Check if the device is in production mode specifically
 */
uint8_t smc_security_is_production_mode(void) {
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_PROD(lc_state) ? 1 : 0;
}

/**
 * Check if the device is in RMA SOP mode
 */
uint8_t smc_security_is_rma_sop_mode(void) {
    uint8_t lc_state = smc_security_get_lc_state();
    return SMC_LC_STATE_IS_RMA_SOP(lc_state) ? 1 : 0;
}

/**
 * Check if device security is in invalid state
 * Includes differential-encoding integrity failures ({~lc, lc} mismatch).
 */
uint8_t smc_security_is_invalid_mode(void) {
    uint8_t raw = smc_security_read_lc_state_raw();

    if (!SMC_LC_STATE_DIFF_IS_VALID(raw)) {
        return 1;
    }

    return SMC_LC_STATE_IS_INVALID(raw & SMC_LC_STATE_MASK) ? 1 : 0;
}
