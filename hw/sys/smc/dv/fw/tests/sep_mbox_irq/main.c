/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "sep_mbox_irq_protocol.h"

/*
 * SEP Mailbox IRQ - SMC consumer of the SEP mailbox interrupts
 *
 * Verifies that, for each of the eight SEP mailbox channels in order, a token pushed by the
 * live SEP CPU latches the SMC-side read interrupt and arrives intact, and that clearing the
 * interrupt drops both status and pending. The SMC drives real MMIO only.
 *
 * The SEP-driven bring-up does not initialise the SMC SRAM stack, so main() is stackless:
 * it makes no function calls and uses only the smc_stackless_test.h macros. The park loops
 * are naked and reached by a jump. Any stack frame in main() hangs the core.
 */
SMC_STACKLESS_ENTRY(sep_mbox_irq_entry)

/* Separate named park loops let an observer of the SMC PC tell pass from fail. Keep the names
 * stable. */
__attribute__((naked, section(".text"), used)) void smu_sep_mailbox_irq_smc_pass_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}
__attribute__((naked, section(".text"), used)) void smu_sep_mailbox_irq_smc_fail_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}

/* SMC outbound filter entry 0 opens the mailbox window. Its CSRs are 64-bit, and each RV64
 * store is a single transaction. */
#define SMC_MBOX_FILTER_IDX 0
#define SMC_FILTER_CONFIG_ADDR \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(SMC_MBOX_FILTER_IDX)
#define SMC_FILTER_START_ADDR \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(SMC_MBOX_FILTER_IDX)
#define SMC_FILTER_END_ADDR SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(SMC_MBOX_FILTER_IDX)

/* Per-channel SMC-facing mailbox port registers. */
#define IN_BASE(ch) (SMU015_MBOX_INBOUND_BASE + (uint32_t)SMU015_MBOX_CH_STRIDE * (uint32_t)(ch))
#define IN_RDATA(ch) (IN_BASE(ch) + MBOX_READ_DATA_OFFSET)
#define IN_STATUS(ch) (IN_BASE(ch) + MBOX_STATUS_OFFSET)
#define IN_RIRQT(ch) (IN_BASE(ch) + MBOX_RIRQT_OFFSET)
#define IN_IRQS(ch) (IN_BASE(ch) + MBOX_IRQS_OFFSET)
#define IN_IRQEN(ch) (IN_BASE(ch) + MBOX_IRQEN_OFFSET)
#define IN_IRQP(ch) (IN_BASE(ch) + MBOX_IRQP_OFFSET)

/* Bounded wait for a word to arrive on channel ch; stackless, like SMC_WAIT_EQ. */
#define SMC_WAIT_NOT_EMPTY_CH(ch, okvar) \
    do { \
        okvar = 0; \
        for (uint32_t _i = 0; _i < (uint32_t)SMU015_POLL_LIMIT; ++_i) { \
            if ((SMC_RD32(IN_STATUS(ch)) & MBOX_STATUS_EMPTY_MASK) == 0u) { \
                okvar = 1; \
                break; \
            } \
        } \
    } while (0)

int main(void) {
    uint32_t ok;

    /* a. Clear the progress, verdict and READY rendezvous scratch and confirm they read 0. */
    SMC_WR32(SMU015_SMC_SCRATCH3_LOCAL, 0u);
    SMC_WR32(SMU015_SMC_SCRATCH10_LOCAL, 0u);
    SMC_WR32(SMU015_SMC_SCRATCH12_LOCAL, 0u);
    SMC_FENCE();
    if (SMC_RD32(SMU015_SMC_SCRATCH3_LOCAL) != 0u) goto fail;
    if (SMC_RD32(SMU015_SMC_SCRATCH10_LOCAL) != 0u) goto fail;
    if (SMC_RD32(SMU015_SMC_SCRATCH12_LOCAL) != 0u) goto fail;

    /* a2. Publish the SMC "up" marker, which is never cleared. The SEP polls it before its
     *     first write to SMC scratch, so READY cannot race the SMC scratch clear. */
    SMC_WR32(SMU015_SMC_SCRATCH2_LOCAL, SMU015_SMC_UP);
    SMC_FENCE();

    /* b. Open the SMC outbound filter over the mailbox region. The window bounds go in before
     *    the configuration. The filter CSRs are not read back: a read returns hardware-fixed
     *    bits that differ from the written value. */
    SMC_WR64(SMC_FILTER_START_ADDR, SMU015_MBOX_FILTER_START);
    SMC_WR64(SMC_FILTER_END_ADDR, SMU015_MBOX_FILTER_END);
    SMC_WR64(SMC_FILTER_CONFIG_ADDR, SMU015_MBOX_FILTER_CFG);
    SMC_FENCE();

    /* c. Wait for the SEP READY rendezvous before touching any mailbox port: the SEP opens
     *    the path to the ports first. */
    SMC_WAIT_EQ(SMU015_SMC_SCRATCH12_LOCAL, SMU015_READY, SMU015_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* d. Arm every channel's read interrupt to fire on any arriving word, read the setup back,
     *    and check that each port starts idle: receive FIFO empty and no interrupt. */
    for (uint32_t ch = 0; ch < SMU015_NUM_CHANNELS; ++ch) {
        SMC_WR32(IN_RIRQT(ch), 0u);
        SMC_WR32(IN_IRQEN(ch), MBOX_IRQ_READ_MASK);
        SMC_FENCE();
        if (SMC_RD32(IN_RIRQT(ch)) != 0u) goto fail;
        if (SMC_RD32(IN_IRQEN(ch)) != MBOX_IRQ_READ_MASK) goto fail;
        if ((SMC_RD32(IN_STATUS(ch)) & MBOX_STATUS_EMPTY_MASK) == 0u) goto fail;
        if (SMC_RD32(IN_IRQS(ch)) != 0u) goto fail;
        if (SMC_RD32(IN_IRQP(ch)) != 0u) goto fail;
    }

    /* e. Signal ARMED: the SEP may now start pushing channel 0. */
    SMC_WR32(SMU015_SMC_SCRATCH3_LOCAL, SMU015_PROGRESS_ARMED);
    SMC_FENCE();

    /* f. Service all eight channels strictly in order. */
    for (uint32_t ch = 0; ch < SMU015_NUM_CHANNELS; ++ch) {
        /* f1. Wait for the SEP to push this channel's token. */
        SMC_WAIT_NOT_EMPTY_CH(ch, ok);
        if (!ok) goto fail;
        /* f2. The arrival must latch the read interrupt on this port. */
        if ((SMC_RD32(IN_IRQS(ch)) & MBOX_IRQ_READ_MASK) == 0u) goto fail;
        if ((SMC_RD32(IN_IRQP(ch)) & MBOX_IRQ_READ_MASK) == 0u) goto fail;
        /* f3. Pop and check the exact per-channel token. */
        if (SMC_RD32(IN_RDATA(ch)) != (SMU015_TOKEN_BASE | ch)) goto fail;
        /* f4. Clear the read interrupt and check that status and pending both drop. */
        SMC_WR32(IN_IRQS(ch), SMU015_W1C_VALUE);
        SMC_FENCE();
        if (SMC_RD32(IN_IRQS(ch)) != 0u) goto fail;
        if (SMC_RD32(IN_IRQP(ch)) != 0u) goto fail;
        /* f5. Hold the port quiet across the no-refire window before the SEP may push again. */
        SMC_DELAY_ITERS(SMU015_NOREFIRE_HOLD_ITERS);
        /* f6. Publish channel done so the SEP advances to the next channel. */
        SMC_WR32(SMU015_SMC_SCRATCH3_LOCAL, SMU015_PROGRESS_ARMED | (ch + 1u));
        SMC_FENCE();
    }

    /* g. Report the pass verdict and park in the named loop. */
    SMC_WR32(SMU015_SMC_SCRATCH10_LOCAL, SMU015_SMC_PASS);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_mailbox_irq_smc_pass_loop");

fail:
    SMC_WR32(SMU015_SMC_SCRATCH10_LOCAL, SMU015_SMC_FAIL);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_mailbox_irq_smc_fail_loop");
}
