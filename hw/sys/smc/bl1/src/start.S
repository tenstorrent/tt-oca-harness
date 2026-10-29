/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC BL1 entry. The SEP BL1 restarts hart 0 here with a core reset pulse, so nothing the
 * SMC Boot ROM set up survives: this code sets its own trap vector, global pointer and stack.
 */

#include "smc_addr.h"
#include "smc_bl1_layout.h"
#include "smc_bl1_status.h"

#define MSTATUS_MIE 0x8

.section .text.start, "ax", @progbits
.global _start
.type _start, @function
_start:
    /* HART0_PARKED tells the SEP that hart 0 is quiescent, which stops being true here. */
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_BL1_SCRATCH_STATUS_TO_SEP)
    ld      t1, 0(t0)
    andi    t1, t1, ~(1 << SMC_BL1_HART0_PARKED_BIT)
    sd      t1, 0(t0)

    csrw    mie, zero
    csrci   mstatus, MSTATUS_MIE
    la      t0, smc_bl1_trap
    csrw    mtvec, t0

    csrr    t0, mhartid
    bnez    t0, smc_bl1_park

.option push
.option norelax
    la      gp, __global_pointer$
.option pop
    la      sp, __stack_top

    la      t0, __data_load
    la      t1, __data_start
    la      t2, __data_end
1:  bgeu    t1, t2, 2f
    ld      t3, 0(t0)
    sd      t3, 0(t1)
    addi    t0, t0, 8
    addi    t1, t1, 8
    j       1b

2:  la      t1, __bss_start
    la      t2, __bss_end
3:  bgeu    t1, t2, 4f
    sd      zero, 0(t1)
    addi    t1, t1, 8
    j       3b

4:  call    main
    j       smc_bl1_park
.size _start, .-_start

/*
 * A trap may come before .bss is cleared, so the handler touches no C state: it writes the
 * POST word itself and parks.
 */
.section .text.smc_bl1_trap, "ax", @progbits
.balign 4
.global smc_bl1_trap
.type smc_bl1_trap, @function
smc_bl1_trap:
    li      t0, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(SMC_BL1_SCRATCH_POST)
    li      t1, SMC_BL1_POST_WORD(SMC_BL1_ERR_TRAP)
    sd      t1, 0(t0)
    j       smc_bl1_park
.size smc_bl1_trap, .-smc_bl1_trap

/*
 * Hart 0 ends here. The SEP may hold it in reset afterwards, which drops dirty D-cache lines,
 * so the status already written is flushed to SRAM first.
 */
.section .text.smc_bl1_park, "ax", @progbits
.global smc_bl1_park
.type smc_bl1_park, @function
smc_bl1_park:
    csrw    mie, zero
    csrci   mstatus, MSTATUS_MIE
    fence
    .word   0xfc000073 /* cflush.d.l1 x0: write back and invalidate the whole L1 D-cache */
    fence
1:  wfi
    j       1b
.size smc_bl1_park, .-smc_bl1_park
