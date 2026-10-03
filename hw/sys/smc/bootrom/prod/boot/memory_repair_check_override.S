// SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
/* SPDX-License-Identifier: Apache-2.0 */

/*
 * Strong memory repair status check override for the SMC production ROM.
 *
 * The weak default hook lives in mbist_check.S and simply returns. This file
 * provides the production memory repair policy while keeping the hook replaceable.
 */

#include "smc_rom_defs.h"

/* Keep it in metal.init section for early execution */
.section .text.metal.init.memory_repair_override
/* Disable linker relaxation to ensure consistent addressing */
.option push
.option norelax

/*
 * Memory repair status check - called after MBIST check passes
 * Validates that memory repair (if required) completed successfully
 *
 * Input: None
 * Output: Does not return if memory repair failed
 * Clobbers: t0, t1, t2, t3
 * Preserves: All other registers including ra
 */
.global __metal_memory_repair_check
.type __metal_memory_repair_check, @function
__metal_memory_repair_check:
    /* Save return address */
    mv      t2, ra

    /* Check MEM_REPAIR_BYPASS strap for early debug (bit 13 in LO register) */
    li      t0, SMC_STRAPS_LO_REG_ADDR_VAL
    lwu     t1, 0(t0)                       /* Read LO straps register */
    li      t0, SMC_STRAP_MEM_REPAIR_BYPASS_MASK_VAL
    and     t0, t1, t0                      /* Check if MEM_REPAIR_BYPASS strap is asserted */
    bnez    t0, memory_repair_bypass_enabled /* If bypass enabled, skip memory repair checks */

    /*
     * Check SMU Memory Repair Status - The Memory Domain ROM Depends On
     *
     * CRITICAL: ROM depends on SRAM for runtime operation, so it must validate
     * the SMU memory repair status before using SRAM for stack/data.
     */
    li      t0, DFX_CTRL_STATUS_SMU_REG_ADDR_VAL
    ld      t1, 0(t0)                       /* Read SMU DFT status register */

    /* Check if memory repair was executed (done bit set) */
    andi    t0, t1, DFT_STATUS_MEM_REPAIR_DONE_MASK_VAL
    beqz    t0, memory_repair_complete      /* If not done, assume not required */

    /* Memory repair was executed - check if it succeeded */
    andi    t0, t1, DFT_STATUS_MEM_REPAIR_SUCCESS_MASK_VAL
    beqz    t0, memory_repair_failed        /* If success bit not set, failed */

memory_repair_complete:
    /* SMU memory repair checks passed - update scratchpad and return */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    ld      t1, 0(t0)                       /* Preserve earlier MBIST failure/timeouts */
    li      t3, MBIST_STATUS_FAILED_VAL
    beq     t1, t3, memory_repair_complete_return
    li      t3, MBIST_STATUS_TIMEOUT_VAL
    beq     t1, t3, memory_repair_complete_return
    li      t3, MBIST_STATUS_MEM_BIST_BYPASSED_VAL
    beq     t1, t3, memory_repair_complete_return
    li      t1, MBIST_STATUS_PASSED_VAL
    sd      t1, 0(t0)

    /* Restore return address and return */
memory_repair_complete_return:
    mv      ra, t2
    ret

memory_repair_failed:
    /*
     * Memory repair reported failure - check OTP SMC_CONFIG bit 15 (DFT ignore error flag)
     * Hardware bug workaround: If OTP SMC_CONFIG bit 15 is set, mem_repair/mbist
     * can report false errors. Ignore the error and continue booting.
     */
    li      t0, SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR_VAL                /* SMC_CONFIG eFuse register address */
    ld      t1, 0(t0)                                                /* Read SMC_CONFIG register */
    li      t0, SMC_EFUSE_SMC_CONFIG_DFT_IGNORE_ERROR_MASK_VAL       /* 0x8000 exceeds andi immediate range */
    and     t1, t1, t0                                               /* Check bit 15 (DFT ignore) */
    bnez    t1, memory_repair_error_ignored                          /* If bit 15 set, ignore error */

    /* Bit 15 not set - treat as real failure and halt */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_MEM_REPAIR_FAILED_VAL
    sd      t1, 0(t0)

    /* Halt CPU - memory repair failure is critical */
memory_repair_halt_loop:
    wfi                                     /* Wait for interrupt (low power) */
    j       memory_repair_halt_loop         /* Infinite loop */

memory_repair_error_ignored:
    /* OTP SMC_CONFIG bit 15 is set - ignore mem_repair error and continue boot */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_MEM_REPAIR_FAILED_VAL     /* Report actual failure status */
    sd      t1, 0(t0)

    /* Restore return address and continue normal boot */
    mv      ra, t2
    ret

/*
 * Memory repair bypass handler for early debug.
 * When MEM_REPAIR_BYPASS strap is asserted, skip memory repair validation
 * and continue with normal boot execution. Sets scratchpad to MEM_REPAIR_BYPASSED
 * to indicate that memory repair checks were bypassed.
 *
 * WARNING: This bypasses critical memory repair validation checks and should
 * only be used for early debug/bringup when memory is known to be reliable or
 * when debugging boot issues that occur before memory repair validation completes.
 */
memory_repair_bypass_enabled:
    /* Set scratchpad register 15 to indicate bypass mode for external visibility */
    li      t0, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li      t1, MBIST_STATUS_MEM_REPAIR_BYPASSED_VAL
    sd      t1, 0(t0)

    /* Restore return address and continue normal boot */
    mv      ra, t2
    ret

.option pop
