/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Security Utilities
 * Device lifecycle and security mode detection.
 */

#ifndef SMC_SECURITY_H
#define SMC_SECURITY_H

#include <stdint.h>
#include "smc_rom_defs.h" /* For SMC_LC_STATE_MASK */

/*
 * Lifecycle State (LC) Values and Security Mode Definitions
 * Based on main system specification
 */

/* LC State Values per main system specification */
#define SMC_LC_STATE_TEST_DEV 0x0          /* 4'b0000 - Test/Development mode */
#define SMC_LC_STATE_PROD 0x1              /* 4'b0001 - Production mode */
#define SMC_LC_STATE_PROD_END 0x8          /* 4'b1000 - Production end mode */
#define SMC_LC_STATE_INVALID 0xF           /* 4'b1111 - Invalid / encoding error */
#define SMC_LC_STATE_RMA_SOP_MASK 0xE      /* 4'b001X - RMA SoP mask (bits 3:1) */
#define SMC_LC_STATE_RMA_SOP_VALUE 0x2     /* 4'b0010/0011 - RMA SoP pattern */
#define SMC_LC_STATE_RMA_CHIPLET_MASK 0xC  /* 4'b01XX - RMA Chiplet mask (bits 3:2) */
#define SMC_LC_STATE_RMA_CHIPLET_VALUE 0x4 /* 4'b0100-0111 - RMA Chiplet pattern */

/*
 * SEP sends LC_STATE differentially encoded as an 8-bit value:
 *   {~lc_state[3:0], lc_state[3:0]}
 * SMC latches the full byte in CHIP_CONFIG.LC_STATE; the low nibble is the
 * decoded lifecycle value when the high nibble equals its bitwise complement.
 */
#define SMC_LC_STATE_NIBBLE_MASK 0xF
#define SMC_LC_STATE_DIFF_IS_VALID(raw) \
    (((((uint8_t)(raw)) >> 4) & SMC_LC_STATE_NIBBLE_MASK) == \
     ((uint8_t)(~(uint8_t)(raw)) & SMC_LC_STATE_NIBBLE_MASK))

/* Lifecycle state check helper macros */
#define SMC_LC_STATE_IS_TEST_DEV(lc_state) ((lc_state) == SMC_LC_STATE_TEST_DEV)
#define SMC_LC_STATE_IS_PROD(lc_state) ((lc_state) == SMC_LC_STATE_PROD)
#define SMC_LC_STATE_IS_PROD_END(lc_state) ((lc_state) == SMC_LC_STATE_PROD_END)
#define SMC_LC_STATE_IS_RMA_SOP(lc_state) \
    (((lc_state)&SMC_LC_STATE_RMA_SOP_MASK) == SMC_LC_STATE_RMA_SOP_VALUE)
#define SMC_LC_STATE_IS_RMA_CHIPLET(lc_state) \
    (((lc_state)&SMC_LC_STATE_RMA_CHIPLET_MASK) == SMC_LC_STATE_RMA_CHIPLET_VALUE)
#define SMC_LC_STATE_IS_INVALID(lc_state) \
    (!(SMC_LC_STATE_IS_TEST_DEV(lc_state) || SMC_LC_STATE_IS_PROD(lc_state) || \
       SMC_LC_STATE_IS_PROD_END(lc_state) || SMC_LC_STATE_IS_RMA_SOP(lc_state) || \
       SMC_LC_STATE_IS_RMA_CHIPLET(lc_state)))

/*
 * Security mode determination for SMC ROM:
 * - SECURE: Only PROD and PROD_END restrict memory access and prohibit JUMP
 * - UNSECURE: All other valid states (TEST_DEV, PROD_DBG, RMA_SoP, RMA_CHIPLET)
 *   allow unrestricted access and all OCCP commands
 *
 * Note: PROD_DBG uses same encoding as PROD (0x1) but is treated as unsecure
 * by SMC ROM to allow debug access. Upper layers distinguish PROD vs PROD_DBG.
 */
#define SMC_LC_STATE_IS_SECURE(lc_state) \
    (SMC_LC_STATE_IS_PROD(lc_state) || SMC_LC_STATE_IS_PROD_END(lc_state))

/**
 * Get the current lifecycle (LC) state from hardware
 * @return 4-bit LC state value, or SMC_LC_STATE_INVALID if the differentially
 *         encoded register value fails integrity (high nibble != ~low nibble)
 */
uint8_t smc_security_get_lc_state(void);

/**
 * Check if the device is in secure mode (PROD or PROD_END)
 * Note: PROD_DBG uses same encoding as PROD but is treated as unsecure
 * @return 1 if in secure mode, 0 otherwise
 */
uint8_t smc_security_is_secure_mode(void);

/**
 * Check if the device is in production mode specifically
 * @return 1 if in production mode, 0 otherwise
 */
uint8_t smc_security_is_production_mode(void);

/**
 * Check if the device is in RMA SOP mode
 * @return 1 if in RMA SOP mode, 0 otherwise
 */
uint8_t smc_security_is_rma_sop_mode(void);

/**
 * Check if the device is in invalid mode
 * @return 1 if in invalid mode, 0 otherwise
 */
uint8_t smc_security_is_invalid_mode(void);

#endif /* SMC_SECURITY_H */
