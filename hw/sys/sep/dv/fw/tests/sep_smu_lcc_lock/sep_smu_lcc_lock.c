/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_lcc_lock - the DEMOTE lock refuses a later demote.
 *
 * DEMOTE_1 and DEMOTE_2 each carry a write-one-to-set demote bit and a
 * write-one-to-set lock bit; firmware can set demote only while lock is clear,
 * and both hold until SEP cold reset (lifecycle controller specification,
 * "Demote lock behavior"). A lock placed on a register whose demote is already
 * set cannot show a refusal, because a set-only bit has nothing left to refuse.
 * This image therefore locks DEMOTE_1 while its demote bit is still clear and
 * then asks for the demote; the register must stay clear. DEMOTE_2, left
 * unlocked, takes the same write, which shows the write path is alive and the
 * zero read back from DEMOTE_1 is a refusal.
 *
 * The bench half reads the same outcome at the SMU boundary: the DEMOTE_2
 * output moves and the DEMOTE_1 output does not. Both postures the consumers
 * compare against come from the lifecycle specification for the sensed state.
 *
 * Stages, each with its own fail loop so a failure names the step:
 *   1. FEAT_CTRL is captured and both DEMOTE registers start clear and
 *      unlocked.
 *   2. DEMOTE_1.lock takes and reads back with demote still clear.
 *   3. A DEMOTE_1 demote write, alone and together with lock, leaves demote
 *      clear.
 *   4. DEMOTE_2.demote takes and reads back (the live control).
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
 * later stage fails. */
#define SCRATCH(n) SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(n)
#define SC_FEAT_BASE_LO SCRATCH(1)
#define SC_DEMOTE_1_LOCKED SCRATCH(2)
#define SC_DEMOTE_1_AFTER_WRITE SCRATCH(3)
#define SC_STAGE SCRATCH(4)

#define STAGE_ENTER 0x1CC10000u

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_lock_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_lock_fail_readable_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_lock_fail_lock_set_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_lock_fail_lock_enforced_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lcc_lock_fail_demote2_loop(void) {
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
    sep_outbound_filter_init();
    WRITE_REG(SC_STAGE, STAGE_ENTER);
    fence_io();

    /* Stage 1: FEAT_CTRL readable; both registers clear and unlocked. */
    WRITE_REG(SC_FEAT_BASE_LO, READ_REG(LCC_FEAT_CTRL));
    fence_io();
    if ((READ_REG(LCC_DEMOTE_1) & (DEMOTE_BIT | LOCK_BIT)) != 0u ||
        (READ_REG(LCC_DEMOTE_2) & (DEMOTE_BIT | LOCK_BIT)) != 0u) {
        sep_smu_lcc_lock_fail_readable_loop();
    }

    /* Stage 2: lock DEMOTE_1 while it is clear. */
    WRITE_REG(LCC_DEMOTE_1, LOCK_BIT);
    fence_io();
    uint32_t locked = READ_REG(LCC_DEMOTE_1);
    WRITE_REG(SC_DEMOTE_1_LOCKED, locked);
    fence_io();
    if ((locked & (DEMOTE_BIT | LOCK_BIT)) != LOCK_BIT) {
        sep_smu_lcc_lock_fail_lock_set_loop();
    }

    /* Stage 3: the locked register refuses the demote, written alone and
     * written together with the lock bit. */
    WRITE_REG(LCC_DEMOTE_1, DEMOTE_BIT);
    fence_io();
    WRITE_REG(LCC_DEMOTE_1, DEMOTE_BIT | LOCK_BIT);
    fence_io();
    uint32_t after = READ_REG(LCC_DEMOTE_1);
    WRITE_REG(SC_DEMOTE_1_AFTER_WRITE, after);
    fence_io();
    if ((after & (DEMOTE_BIT | LOCK_BIT)) != LOCK_BIT) {
        sep_smu_lcc_lock_fail_lock_enforced_loop();
    }

    /* Stage 4: the same write to the unlocked DEMOTE_2 takes. */
    WRITE_REG(LCC_DEMOTE_2, DEMOTE_BIT);
    fence_io();
    if ((READ_REG(LCC_DEMOTE_2) & DEMOTE_BIT) == 0u) {
        sep_smu_lcc_lock_fail_demote2_loop();
    }

    sep_smu_lcc_lock_pass_loop();
}
