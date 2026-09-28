/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/*
 * rom_wipe.S — SRAM shredding routine (noreturn)
 *
 * Performs three stages:
 *   1) Register scrub of all writable RV32E GPRs.
 *   2) Fast SRAM "flash erase" pass using a Weyl-sequence + address mix pattern.
 *   3) Full SRAM shred with xoshiro128++ running purely in registers.
 *
 * Called from rom_trigger_unrecoverable() after fault notification when
 * shred gating is enabled. Performs ROM_KM_SHRED_ITER passes, then
 * executes ebreak to halt the CPU permanently.
 *
 * Register allocation (RV32E — 16 registers only):
 *   x0  (zero)  hardwired zero
 *   x1  (ra)    scrub target (routine never returns)
 *   x2  (sp)    scrub target (stack is in SRAM being destroyed)
 *   x5  (t0)    flash Weyl increment / pass counter
 *   x6  (t1)    pass limit (ROM_KM_SHRED_ITER)
 *   x8  (s0)    SRAM write pointer / PRNG state base ptr
 *   x9  (s1)    SRAM end address
 *   x10 (a0)    PRNG s[0] / flash write word temp
 *   x11 (a1)    PRNG s[1]
 *   x12 (a2)    PRNG s[2]
 *   x13 (a3)    PRNG s[3]
 *   x14 (a4)    PRNG output / flash pattern state
 *   x15 (a5)    temp / flash Weyl state
 */

#include "rom_defs.h"
#include "rom_xoshiro_asm.h"

    .section .text
    .global  rom_wipe_shred_sram
    .type    rom_wipe_shred_sram, @function

rom_wipe_shred_sram:
    /*
     * ---- Stage 1: scrub writable CPU registers ----
     * Small immediates so the assembler can emit c.li.
     */
    li   x1,  23
    li   x2,  -31
    li   x3,  6
    li   x4,  -18
    li   x5,  29
    li   x6,  -7
    li   x7,  14
    li   x8,  -25
    li   x9,  3
    li   x10, -12
    li   x11, 27
    li   x12, -2
    li   x13, 19
    li   x14, -21
    li   x15, 11

    /* ---- Load PRNG state from rom_prng_state.s[0..3] ---- */
    la   x8, rom_prng_state
    lw   x10, 0(x8)                /* s[0] */
    lw   x11, 4(x8)                /* s[1] */
    lw   x12, 8(x8)                /* s[2] */
    lw   x13, 12(x8)               /* s[3] */

    /* Escape all-zero absorbing state */
    or   x14, x10, x11
    or   x14, x14, x12
    or   x14, x14, x13
    bnez x14, .Lstate_ok
    li   x10, 1
.Lstate_ok:

    /* ---- Stage 2: fast SRAM flash-erase pass ---- */
    li   x8,  ROM_KM_SRAM_BASE
    li   x9,  ROM_KM_SRAM_END
    li   x15, 0xA5A55A5A
    li   x5,  0x9E3779B9

.Lflash_loop:
    /*
     * Weyl step is a single add per word (very fast), then mix in address so
     * adjacent locations are not simple increments.
     */
    add  x15, x15, x5
    xor  x14, x15, x8
    sw   x14, 0(x8)

    addi x8, x8, 4
    bltu x8, x9, .Lflash_loop

    /* ---- Pass loop setup ---- */
    li   x5,  0                        /* pass counter = 0 */
    li   x6,  ROM_KM_SHRED_ITER         /* total passes */

.Lpass_loop:
    li   x8, ROM_KM_SRAM_BASE      /* write pointer */
    li   x9, ROM_KM_SRAM_END       /* loop end */

    /* ---- Inner loop: overwrite every word in SRAM ---- */
.Lword_loop:
    /* Advance the PRNG, leaving the output word in x14 and using x15 as temp. */
    XOSHIRO128PP_STEP x10, x11, x12, x13, x14, x15

    /* Store xoshiro128++ output word to SRAM */
    sw   x14, 0(x8)

    /* Advance pointer and loop */
    addi x8, x8, 4
    bltu x8, x9, .Lword_loop

    /* ---- Next pass ---- */
    addi x5, x5, 1
    bne  x5, x6, .Lpass_loop

    /* ---- All passes done — halt permanently ---- */
    ebreak

    .size rom_wipe_shred_sram, . - rom_wipe_shred_sram
