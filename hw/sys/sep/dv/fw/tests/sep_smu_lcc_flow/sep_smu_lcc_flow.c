/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_lcc_flow - SEP lifecycle-controller flow, driven from SEP firmware.
 *
 * The SEP LCC is the source of the lifecycle posture that the rest of the
 * chiplet consumes:
 *
 *   SEP eFuse shadow regs -> sep_lifecycle_ctrl -+-> lc_state   -> SMC
 *                                                +-> dbg_disable -> DTP
 *                                                +-> feat_ctrl
 *
 * A single static sample of lc_state at the SMU boundary proves the wire
 * exists; it does not prove the LCC responds to anything or that the posture
 * reaches its consumers.
 *
 * This firmware drives the one input software owns -- the DEMOTE registers --
 * and records what it observes into SEP-local cold scratch.
 *
 * A demote is not required to change FEAT_CTRL. Per sep_lifecycle_ctrl.sv the
 * demotes force feat_ctrl[15:0] and feat_ctrl[31:16] to all-ones, but in
 * TEST_DEV the baseline is already ~(sip_dis | sys_dis), so with a permissive
 * eFuse image those bits are set before any demote and the write is a no-op on
 * FEAT_CTRL. FEAT_CTRL is captured at each step for the testbench to report, and
 * the demote's effect is checked where it is unambiguous: the register readback
 * here, and lcc_demote_state_*_o at the SMU boundary.
 *
 * Stages, each with its own fail loop so a failure names the step:
 *   1. FEAT_CTRL is readable and both DEMOTE registers start clear.
 *   2. DEMOTE_1.demote takes and reads back.
 *   3. DEMOTE_2.demote takes and reads back.
 *   4. DEMOTE_1.lock is write-once: after locking, clearing demote is refused.
 *
 * Stage 4 is what makes stages 2-3 non-vacuous. A register that simply stored
 * whatever software wrote would pass 2 and 3; only the refused write after lock
 * shows the block implements the policy rather than acting as scratch.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

#define LCC_FEAT_CTRL OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR
#define LCC_DEMOTE_1 OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR
#define LCC_DEMOTE_2 OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_2_BASE_ADDR

#define DEMOTE_BIT 0x1u
#define LOCK_BIT 0x2u

/* Results the testbench reads back out of SEP-local cold scratch, so the flow
 * is inspectable even when a later stage fails. Cold scratch is SEP-local: no
 * outbound window is needed for these, unlike the STDOUT mailbox. */
#define SCRATCH(n) OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(n)
#define SC_FEAT_BASE_LO SCRATCH(1)
#define SC_FEAT_D1_LO SCRATCH(2)
#define SC_FEAT_D2_LO SCRATCH(3)
#define SC_STAGE SCRATCH(4)

#define STAGE_ENTER 0x1CC00000u

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_flow_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_flow_fail_readable_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_flow_fail_demote1_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_flow_fail_demote2_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_flow_fail_lock_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

static inline void fence_io(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

int main(void) {
    /* Keep the outbound window open like the other SMU SEP images, even though
     * every result here goes to SEP-local scratch. */
    sep_outbound_filter_init();
    WRITE_REG(SC_STAGE, STAGE_ENTER);
    fence_io();

    /* Stage 1: FEAT_CTRL readable. It is sw=r, so this is the only view
     * software has of the decoded lifecycle profile. */
    uint32_t feat_base = READ_REG(LCC_FEAT_CTRL);
    WRITE_REG(SC_FEAT_BASE_LO, feat_base);
    fence_io();

    /* Start from a known state: both demotes clear, neither locked. */
    WRITE_REG(LCC_DEMOTE_1, 0u);
    WRITE_REG(LCC_DEMOTE_2, 0u);
    fence_io();
    if ((READ_REG(LCC_DEMOTE_1) & (DEMOTE_BIT | LOCK_BIT)) != 0u) {
        sep_smu_lcc_flow_fail_readable_loop();
    }

    /* Stage 2: DEMOTE_1 accepts the write and reads it back. */
    WRITE_REG(LCC_DEMOTE_1, DEMOTE_BIT);
    fence_io();
    if ((READ_REG(LCC_DEMOTE_1) & DEMOTE_BIT) == 0u) {
        sep_smu_lcc_flow_fail_demote1_loop();
    }
    WRITE_REG(SC_FEAT_D1_LO, READ_REG(LCC_FEAT_CTRL));
    fence_io();

    /* Stage 3: DEMOTE_2, same contract as DEMOTE_1. */
    WRITE_REG(LCC_DEMOTE_2, DEMOTE_BIT);
    fence_io();
    if ((READ_REG(LCC_DEMOTE_2) & DEMOTE_BIT) == 0u) {
        sep_smu_lcc_flow_fail_demote2_loop();
    }
    WRITE_REG(SC_FEAT_D2_LO, READ_REG(LCC_FEAT_CTRL));
    fence_io();

    /* Stage 4: DEMOTE_1.lock is write-once. After locking, an attempt to clear
     * demote must be refused. Without this the earlier stages would also pass
     * on a plain scratch register. */
    WRITE_REG(LCC_DEMOTE_1, DEMOTE_BIT | LOCK_BIT);
    fence_io();
    WRITE_REG(LCC_DEMOTE_1, 0u);
    fence_io();
    if ((READ_REG(LCC_DEMOTE_1) & DEMOTE_BIT) == 0u) {
        sep_smu_lcc_flow_fail_lock_loop();
    }

    sep_smu_lcc_flow_pass_loop();
}
