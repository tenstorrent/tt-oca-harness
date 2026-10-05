/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_lcc_flow - SEP lifecycle controller responds to software demotes.
 *
 * The SEP LCC turns the eFuse shadow state into the lifecycle posture the rest
 * of the chiplet consumes: lc_state to SMC, debug disable to DTP, and feature
 * control. A static sample of lc_state at the SMU boundary proves only that the
 * wire exists. This firmware drives the one input software owns, the DEMOTE
 * registers, and records what it observes in SEP-local cold scratch.
 *
 * A demote need not change FEAT_CTRL: in TEST_DEV with a permissive eFuse image
 * the bits a demote forces are already set. The demote is checked where it is
 * unambiguous: the register readback here and the demote state at the SMU
 * boundary.
 *
 * Both demotes end set, so the lifecycle posture the bench compares at the
 * consumers is the one the specification gives for a state with both demotes
 * set. Each demote is locked after it is set; the lock reads back, and the
 * demote bit stays set with it. A refused write is not provable here: demote
 * is write-one-to-set, so once it is set no later write can change it, locked
 * or not. The lock refusing a demote is proven by sep_smu_lcc_lock, which locks
 * a register while it is still clear.
 *
 * Stages, each with its own fail loop so a failure names the step:
 *   1. FEAT_CTRL is captured and both DEMOTE registers start clear and unlocked.
 *   2. DEMOTE_1.demote takes and reads back.
 *   3. DEMOTE_2.demote takes and reads back.
 *   4. DEMOTE_1 and DEMOTE_2 lock with their demote bits set; each reads back
 *      demote and lock both set.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

#define LCC_FEAT_CTRL SEP_TOP_SEP_LIFECYCLE_CTRL_FEAT_CTRL_BASE_ADDR
#define LCC_DEMOTE_1 SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR
#define LCC_DEMOTE_2 SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_2_BASE_ADDR

#define DEMOTE_BIT SEP_LIFECYCLE_CTRL__DEMOTE__DEMOTE_bm
#define LOCK_BIT SEP_LIFECYCLE_CTRL__DEMOTE__LOCK_bm

/* Results kept in SEP-local cold scratch so the flow is inspectable even when a
 * later stage fails. Cold scratch needs no outbound window, unlike the STDOUT
 * mailbox. */
#define SCRATCH(n) SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(n)
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

    /* Stage 1: read-only FEAT_CTRL is the only software view of the decoded
     * lifecycle profile. */
    uint32_t feat_base = READ_REG(LCC_FEAT_CTRL);
    WRITE_REG(SC_FEAT_BASE_LO, feat_base);
    fence_io();

    /* Both registers must start clear and unlocked. */
    if ((READ_REG(LCC_DEMOTE_1) & (DEMOTE_BIT | LOCK_BIT)) != 0u ||
        (READ_REG(LCC_DEMOTE_2) & (DEMOTE_BIT | LOCK_BIT)) != 0u) {
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

    /* Stage 4: each lock commits its demoted state; demote and lock read back
     * set together. */
    WRITE_REG(LCC_DEMOTE_1, LOCK_BIT);
    WRITE_REG(LCC_DEMOTE_2, LOCK_BIT);
    fence_io();
    if ((READ_REG(LCC_DEMOTE_1) & (DEMOTE_BIT | LOCK_BIT)) != (DEMOTE_BIT | LOCK_BIT) ||
        (READ_REG(LCC_DEMOTE_2) & (DEMOTE_BIT | LOCK_BIT)) != (DEMOTE_BIT | LOCK_BIT)) {
        sep_smu_lcc_flow_fail_lock_loop();
    }

    sep_smu_lcc_flow_pass_loop();
}
