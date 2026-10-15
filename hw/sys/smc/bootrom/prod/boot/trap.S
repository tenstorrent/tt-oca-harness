/* Copyright 2019 SiFive, Inc */
/* SPDX-License-Identifier: Apache-2.0 */

#include "smc_rom_defs.h"

#define METAL_MSTATUS_MIE_SHIFT 8
#define METAL_MSTATUS_MPP_M     3
#define METAL_MSTATUS_MPP_SHIFT 11

#define METAL_MTVEC_MODE_MASK   3

/* void _metal_trap(int ecode)
 *
 * Trigger a machine-mode trap with exception code ecode
 */
.global _metal_trap
.type _metal_trap, @function

_metal_trap:

    /* Store the instruction which called _metal_trap in mepc */
    addi t0, ra, -1
    csrw mepc, t0

    /* Set mcause to the desired exception code */
    csrw mcause, a0

    /* Read mstatus */
    csrr t0, mstatus

    /* Set MIE=0 */
    li t1, -1
    xori t1, t1, METAL_MSTATUS_MIE_SHIFT
    and t0, t0, t1

    /* Set MPP=M */
    li t1, METAL_MSTATUS_MPP_M
    slli t1, t1, METAL_MSTATUS_MPP_SHIFT
    or t0, t0, t1

    /* Write mstatus */
    csrw mstatus, t0

    /* Read mtvec */
    csrr t0, mtvec

    /*
     * Mask the mtvec MODE bits
     * Exceptions always jump to mtvec.BASE regardless of the vectoring mode.
     */
    andi t0, t0, METAL_MTVEC_MODE_MASK

    /* Jump to mtvec */
    jr t0


/*
 * For sanity's sake we set up an early trap vector that just does nothing.
 * If you end up here then there's a bug in the early boot code somewhere.
 */
.section .text.metal.init.trapvec
.global early_trap_vector
.align 2
early_trap_vector:
    .cfi_startproc
    csrr t0, mcause
    csrr t1, mepc
    csrr t2, mtval

    /*
     * Unused ROM contains EBREAK instructions. Classify a breakpoint whose
     * MEPC is in [__rom_used_end, __rom_end) as a ROM padding trap.
     */
    li   t3, 3
    bne  t0, t3, generic_trap_fail

    la   t3, __rom_used_end
    la   t4, __rom_end
    bltu t1, t3, generic_trap_fail
    bgeu t1, t4, generic_trap_fail

    li t5, SMC_SCRATCH_MBIST_STATUS_ADDR_VAL
    li t6, ROM_PADDING_TRAP_STATUS_VAL
    sd t6, 0(t5)
    j trap_infinite_loop

generic_trap_fail:
    # Store 0xffffffff to scratch 0 (Embedded test fail)
    li t5, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0)
    li t6, 0xffffffff
    sd t6, 0(t5)

trap_infinite_loop:
    j trap_infinite_loop
    .cfi_endproc
