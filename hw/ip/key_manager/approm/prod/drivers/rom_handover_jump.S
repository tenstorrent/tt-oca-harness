/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/*
 * @file rom_handover_jump.S
 * @brief Stack-less SRAM scramble and jump to mutable firmware.
 *
 * Called from rom_handover_finish() (C) with all IRQs already disabled and
 * all SRAM write-locks in place.
 *
 * Contract (enforced by rom_handover_finish before calling here):
 *   - All CPU IRQs are masked (maskirq = 0xFFFFFFFF).
 *   - All KMCSR and mailbox IRQ enables are cleared.
 *   - SRAM write-lock regions for firmware image and rom_persist are set.
 *
 * This routine additionally sets SRAM_EXEC_MODE.enable (triple write) immediately
 * before the jalr, so SRAM execution is enabled for the first time in the
 * narrowest possible window before the jump.
 *
 * That write also arms the ROM lockout.  Arming is not revocation: the ROM is
 * revoked on the first committed instruction fetch from write-locked SRAM, which
 * is the jalr's target.  Everything this routine executes after the triple write
 * is still ROM code, and stays legal for exactly that reason.  From the landing
 * onward the ROM is unreadable and unexecutable until the next warm reset, so
 * mutable firmware can neither call back into ROM nor read rom_persist.
 *
 * Algorithm:
 *   1. Overwrite the entire SRAM (0x8000..0xFFFF inclusive) with a
 *      register-seeded xoshiro128++ pseudorandom pattern.
 *      - Hardware silently drops writes to write-locked regions (firmware image
 *        and rom_persist), so only unlocked data (ROM stack, .data, .bss,
 *        message buffers, etc.) is actually overwritten.
 *      - The write-lock for SRAM_WRITE_LOCK_ERR is disabled by the C caller,
 *        preventing spurious unrecoverable faults from the locked-region writes.
 *   2. fence — ensure all stores complete before register clear.
 *   3. Clear all general-purpose registers (x1-x15 in RV32E).
 *   4. Jump to SRAM base (0x8000).
 *
 * Note on step ordering: locking (SRAM regions, OTP, persist) and IRQ disable
 * are performed in C (rom_handover_finish) before this routine.  This is
 * necessary because those C operations require a valid stack and function-call
 * conventions, both of which are destroyed by the scramble here.
 *
 * Register usage (RV32E: x0-x15 only):
 *   a0 (x10) = xoshiro state s[0]     (PRNG, caller-supplied)
 *   a1 (x11) = xoshiro state s[1]     (PRNG, caller-supplied)
 *   a2 (x12) = xoshiro state s[2]     (PRNG, caller-supplied)
 *   a3 (x13) = xoshiro state s[3]     (PRNG, caller-supplied)
 *   a4 (x14) = xoshiro result (word written to SRAM)
 *   a5 (x15) = xoshiro scratch (temp)
 *   t0 (x5)  = SRAM write pointer
 *   t1 (x6)  = SRAM end address (exclusive)
 */

#include "rom_xoshiro_asm.h"
#include "key_manager_addr.h"
#include "rom_defs.h"

    .section .text, "ax"
    .global rom_handover_jump
    .type   rom_handover_jump, @function

rom_handover_jump:
    /* a0-a3: initial xoshiro128++ state (from caller) */
    li   t0, ROM_KM_SRAM_BASE       /* t0 = SRAM base (write pointer) */
    li   t1, ROM_KM_SRAM_END        /* t1 = SRAM end  (exclusive) */

.Lscramble_loop:
    bgeu t0, t1, .Lscramble_done

    /* One xoshiro128++ step: a4 = output word, a0-a3 advanced, a5 clobbered. */
    XOSHIRO128PP_STEP a0, a1, a2, a3, a4, a5

    /* Write scramble word to SRAM */
    sw   a4, 0(t0)
    addi t0, t0, 4

    j    .Lscramble_loop

.Lscramble_done:
    /* Ensure all SRAM stores complete before we destroy the register file. */
    fence

    /* Load jump target into t0 (x5) BEFORE clearing all other registers. */
    li   x5,  ROM_KM_SRAM_BASE      /* t0 = mutable firmware entry */

    /* Clear all GPRs (x1-x15, skip x0 which is hardwired zero).
     * x5 is cleared last because it holds the jump target. */
    li   x1,  0
    li   x2,  0
    li   x3,  0
    li   x4,  0
    /* x5 (t0): keep, cleared after jump */
    li   x6,  0
    li   x7,  0
    li   x8,  0
    li   x9,  0
    li   x10, 0
    li   x11, 0
    li   x12, 0
    li   x13, 0
    li   x14, 0
    li   x15, 0

    /* Enable SRAM execution mode immediately before the jump (triple write).
     *
     * x1 = KEY_MANAGER_KMCSR_SRAM_EXEC_MODE_BASE_ADDR (from key_manager_addr.h)
     * x2 = write value (enable bit = 1)
     *
     * The bit is write-1-only (woset) so writing 1 is idempotent.
     * Three identical stores harden against voltage-glitch skip attacks
     * (the same convention used for SRAM write-lock in rom_kmcsr.c).
     *
     * This is the arming write for the ROM lockout; the instructions below
     * still fetch from ROM and must, which is why the lockout engages on the
     * fetch at the jump target rather than here.
     *
     * After the three stores x1 and x2 are zeroed before the jump so the
     * mutable firmware starts with a clean register file.
     */
    li   x1,  KEY_MANAGER_KMCSR_SRAM_EXEC_MODE_BASE_ADDR
    li   x2,  1                /* enable = 1 */
    sw   x2,  0(x1)
    sw   x2,  0(x1)
    sw   x2,  0(x1)
    li   x1,  0
    li   x2,  0

    /* Jump to mutable firmware.  x5 holds the SRAM base; jalr zero,0(x5) writes
     * the return address to x0 (discarded) and jumps there.  x5 still holds the
     * base on landing but the mutable firmware initialises its own state. */
    jalr zero, 0(x5)

    .size rom_handover_jump, . - rom_handover_jump
