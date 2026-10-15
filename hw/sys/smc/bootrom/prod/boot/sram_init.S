// SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
/* SPDX-License-Identifier: Apache-2.0 */

/*
 * Early SRAM initialization using the hardware AXI zeroer.
 *
 * This file intentionally avoids stack usage. It runs from entry.S before the
 * C runtime and stack are initialized.
 */

/* Keep it in metal.init section with _enter */
.section .text.metal.init.scrub
/* Disable linker relaxation */
.option push
.option norelax

#include "smc_rom_defs.h"

/*
 * Clear scratch registers used for SMC/SEP coordination.
 * Scratch register 15 is preserved because it carries MBIST/memory repair status.
 */
.global __metal_clear_coordination_scratch_regs
.type __metal_clear_coordination_scratch_regs, @function
__metal_clear_coordination_scratch_regs:
    mv      t6, ra

    /* Scratch Register 9: SMC status to SEP */
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_SCRATCH_SMC_STATUS_TO_SEP)
    sd      zero, 0(t0)

    /* Scratch Register 8: manifest address */
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_SCRATCH_MANIFEST_ADDR)
    sd      zero, 0(t0)

    /* Scratch Register 11: status buffer address */
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_SCRATCH_STATUS_BUFFER_ADDR)
    sd      zero, 0(t0)

    /* Scratch Register 13: SEP safe SRAM start */
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_SCRATCH_SEP_SAFE_SRAM_START)
    sd      zero, 0(t0)

    /* Scratch Register 14: SEP safe SRAM size */
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_SCRATCH_SEP_SAFE_SRAM_SIZE)
    sd      zero, 0(t0)

    mv      ra, t6
    ret

/*
 * Early SRAM initialization.
 *
 * Hardware auto-zero is expected by default. Manual zeroing is performed only
 * when SRAM_AUTO_ZERO_DISABLE strap or OTP SMC_CONFIG[7] requests it.
 */
.global __metal_sram_init_early
.type __metal_sram_init_early, @function
__metal_sram_init_early:
    mv      t6, ra

    /* Check SRAM_AUTO_ZERO_DISABLE strap. */
    li      t0, SMC_STRAPS_LO_REG_ADDR_VAL
    lwu     t1, 0(t0)
    li      t2, SMC_STRAP_SRAM_AUTO_ZERO_DISABLE_MASK_VAL
    and     t1, t1, t2
    bnez    t1, perform_manual_zeroing

    /* Check OTP SMC_CONFIG[7] auto-zero disable override. */
    li      t0, SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR_VAL
    ld      t1, 0(t0)
    li      t2, SMC_EFUSE_SMC_CONFIG_SRAM_AUTO_ZERO_DISABLE_MASK_VAL
    and     t1, t1, t2
    beqz    t1, skip_early_scrub

perform_manual_zeroing:
    li      t3, SMC_SRAM_BASE
    li      t4, SMC_SRAM_SIZE_VAL

    /* Disable machine interrupts while configuring the accelerator. */
    li      t5, 8
    csrrc   t5, mstatus, t5

    /* Configure and start the hardware zeroer. */
    li      t0, SMC_ZEROER_DEST_ADDR_REG_VAL
    sd      t3, 0(t0)

    li      t0, SMC_ZEROER_SIZE_REG_VAL
    sd      t4, 0(t0)

    li      t0, SMC_ZEROER_CTRL_STATUS_REG_VAL
    sd      zero, 0(t0)

wait_early_zeroer_complete:
    li      t0, SMC_ZEROER_CTRL_STATUS_REG_VAL
    ld      t1, 0(t0)
    li      t2, SMC_ZEROER_BUSY_MASK_VAL
    and     t1, t1, t2
    bnez    t1, wait_early_zeroer_complete

    csrw    mstatus, t5

skip_early_scrub:
    mv      ra, t6
    ret

.option pop
