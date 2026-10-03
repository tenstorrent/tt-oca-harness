// SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
/* SPDX-License-Identifier: Apache-2.0 */

/*
 * Strong MBIST status check override for the SMC production ROM.
 *
 * The weak default hook lives in mbist_check.S and simply returns. This file
 * provides the production MBIST policy while keeping the hook replaceable.
 */

#include "smc_rom_defs.h"

/* Keep it in metal.init section for early execution */
.section .text.metal.init.mbist_override
/* Disable linker relaxation to ensure consistent addressing */
.option push
.option norelax

/*
 * Early MBIST status check - must be called before stack setup
 * No stack operations allowed - uses only registers
 *
 * Input: None
 * Output: Does not return if MBIST failed. Loops in wfi if failure detected.
 * Clobbers: t0, t1, t2, t3
 * Preserves: All other registers including ra
 */
.global __metal_mbist_early_check
.type __metal_mbist_early_check, @function
__metal_mbist_early_check:
    /* Save return address - no stack available yet */
    mv      t3, ra

    /* Check MEM_BIST_BYPASS strap for early debug (bit 54 in HI register) */
    li      t0, SMC_STRAPS_HI_REG_ADDR_VAL
    lwu     t1, 0(t0)                       /* Read HI straps register */
    li      t2, SMC_STRAP_MEM_BIST_BYPASS_MASK_VAL
    and     t2, t1, t2                      /* Check if MEM_BIST_BYPASS strap is asserted */
    bnez    t2, mbist_bypass_enabled        /* If bypass enabled, skip MBIST checks */

    /* Initialize scratchpad register 15 to indicate MBIST check starting */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_RUNNING_VAL
    sd      t1, 0(t0)

    /*
     * Check SMU MBIST Status - The Memory Domain ROM Depends On
     *
     * The SMU DFT status validates the SRAM region (0xC0060000+) that ROM will use.
     */
    li      t0, DFX_CTRL_STATUS_SMU_REG_ADDR_VAL
    ld      t1, 0(t0)                       /* Read SMU DFT status register */

    /* Check if MBIST was executed (done bit set) */
    andi    t2, t1, DFT_STATUS_MBIST_DONE_MASK_VAL
    beqz    t2, mbist_check_complete        /* If not done, assume not required */

    /* MBIST was executed - check if it passed */
    li      t0, DFT_STATUS_MBIST_PASS_MASK_VAL
    and     t2, t1, t0
    bnez    t2, mbist_check_complete        /* If pass bit set, continue */

    /* Check if MBIST aborted due to timeout */
    li      t0, DFT_STATUS_MBIST_ABORT_MASK_VAL
    and     t2, t1, t0
    bnez    t2, mbist_timeout               /* If abort bit set, handle timeout */

    /* MBIST done but not passed and not aborted = failed */
    j       mbist_failed

mbist_check_complete:
    /* SMU MBIST checks passed - return without updating scratchpad
     * Memory repair check will set final status after it completes */

    /* Restore return address and continue normal boot */
    mv      ra, t3
    ret

mbist_timeout:
    /* MBIST aborted due to timeout - set scratchpad and halt */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_TIMEOUT_VAL
    sd      t1, 0(t0)
    j       mbist_halt_cpu

mbist_failed:
    /*
     * MBIST reported failure - check OTP SMC_CONFIG bit 15 (MBIST ignore error flag)
     * Hardware bug workaround: If OTP SMC_CONFIG bit 15 is set, mem_repair/mbist
     * can report false errors. Ignore the error and continue booting.
     */
    li      t0, SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR_VAL                /* SMC_CONFIG eFuse register address */
    ld      t1, 0(t0)                                                /* Read SMC_CONFIG register */
    li      t2, SMC_EFUSE_SMC_CONFIG_DFT_IGNORE_ERROR_MASK_VAL       /* 0x8000 exceeds andi immediate range */
    and     t1, t1, t2                                               /* Check bit 15 (DFT ignore) */
    bnez    t1, mbist_error_ignored                                  /* If bit 15 set, ignore error */

    /* Bit 15 not set - treat as real failure and halt */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_FAILED_VAL
    sd      t1, 0(t0)
    j       mbist_halt_cpu

mbist_error_ignored:
    /* OTP SMC_CONFIG bit 15 is set - ignore MBIST error and continue boot */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_FAILED_VAL     /* Report actual failure status */
    sd      t1, 0(t0)

    /* Restore return address and continue normal boot */
    mv      ra, t3
    ret

/*
 * MBIST bypass handler for early debug.
 * When MEM_BIST_BYPASS strap is asserted, skip MBIST validation and continue
 * with normal boot execution. Sets scratchpad to MEM_BIST_BYPASSED to indicate
 * that MBIST checks were bypassed.
 */
mbist_bypass_enabled:
    /* Set scratchpad register 15 to indicate bypass mode for external visibility */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_MEM_BIST_BYPASSED_VAL
    sd      t1, 0(t0)

    /* Restore return address and continue normal boot */
    mv      ra, t3
    ret

mbist_halt_cpu:
    /*
     * Halt CPU execution - memory is not reliable
     * Use low-power wait-for-interrupt loop
     * External debugger can read scratchpad register 15 for failure reason
     */
mbist_halt_loop:
    wfi                                     /* Wait for interrupt (low power) */
    j       mbist_halt_loop                 /* Infinite loop - do not proceed */

.option pop
