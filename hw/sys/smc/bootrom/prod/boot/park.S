/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Park hart 0 so that the SEP may reset it.
 *
 * A core reset applies without draining the hart, so every dirty L1 D-cache line is written
 * back before HART0_PARKED is published. Nothing after the flush may touch memory: the
 * routine uses no stack and never returns, so it is also safe to enter from the trap handler.
 */

#include "smc_rom_defs.h"

#define MSTATUS_MIE 0x8

.section .text.smc_park_hart0, "ax", @progbits
.global smc_park_hart0
.type smc_park_hart0, @function
smc_park_hart0:
    csrw    mie, zero
    csrci   mstatus, MSTATUS_MIE

    fence
    .word   0xfc000073 /* cflush.d.l1 x0: write back and invalidate the whole L1 D-cache */
    fence

    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_SCRATCH_SMC_STATUS_TO_SEP)
    ld      t1, 0(t0)
    ori     t1, t1, (1 << SMC_SEP_STATUS_HART0_PARKED_BIT)
    sd      t1, 0(t0)

/* The parked loop; testbenches locate it by this symbol. */
.global smc_park_hart0_wfi
smc_park_hart0_wfi:
    wfi
    j       smc_park_hart0_wfi
.size smc_park_hart0, .-smc_park_hart0
