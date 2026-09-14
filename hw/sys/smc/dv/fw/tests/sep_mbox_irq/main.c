/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "sep_mbox_irq_protocol.h"

/*
 * SEP_SMU_015  sep_mbox_irq  --  SMC (CONSUMER) firmware.
 *
 * Real SMC firmware is the SOLE functional consumer of the eight SEP mailbox
 * source interrupts. The SEP CPU pushes one channel token at a time; the SMC
 * arms every inbound channel's read IRQ, then for ch=0..7 in order: waits that
 * inbound port non-empty, checks the latched arrival IRQ, pops+verifies the
 * token (0x15000000|ch), W1C-clears the read IRQ, reads back IRQS=0/IRQP=0,
 * holds the port quiet across the no-refire window, and publishes per-channel
 * progress on scratch3. After channel 7 it publishes the SMU015_SMC_PASS verdict
 * on scratch10 and parks in a named loop. No force/deposit: the SMC opens its
 * OWN outbound egress filter over the mailbox window and drives only real
 * AXI-lite MMIO.
 *
 * STACKLESS (smc_stackless_test.h): the SMU cocotb / SEP-driven boot does not
 * initialise the SMC SRAM stack, so main() makes no function calls and uses
 * only the SMC_* absolute-MMIO/poll macros. The named pass/fail loops are NAKED
 * and reached by a tail `j` (no stack); any `add sp,sp,-N` in main hangs the
 * core.
 */
SMC_STACKLESS_ENTRY(sep_mbox_irq_entry)

/* Named park loops (naked -> no stack; reached by tail-jump from main). A cocotb
 * SMC-PC watch resolves these symbols from the SMC test.dis and confirms the SMC
 * parked in the correct one. */
__attribute__((naked, section(".text"), used)) void smu_sep_mailbox_irq_smc_pass_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}
__attribute__((naked, section(".text"), used)) void smu_sep_mailbox_irq_smc_fail_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}

/* SMC outbound egress filter entry 0 (opens the mailbox window; 64-bit CSRs,
 * single stores on RV64). Addresses come from the generated SMC register map. */
#define SMC_MBOX_FILTER_IDX 0
#define SMC_FILTER_CONFIG_ADDR \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(SMC_MBOX_FILTER_IDX)
#define SMC_FILTER_START_ADDR \
    SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(SMC_MBOX_FILTER_IDX)
#define SMC_FILTER_END_ADDR SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(SMC_MBOX_FILTER_IDX)

/* Per-channel inbound (SMC-facing) mailbox register absolute addresses. */
#define IN_BASE(ch) (SMU015_MBOX_INBOUND_BASE + (uint32_t)SMU015_MBOX_CH_STRIDE * (uint32_t)(ch))
#define IN_RDATA(ch) (IN_BASE(ch) + MBOX_READ_DATA_OFFSET)
#define IN_STATUS(ch) (IN_BASE(ch) + MBOX_STATUS_OFFSET)
#define IN_RIRQT(ch) (IN_BASE(ch) + MBOX_RIRQT_OFFSET)
#define IN_IRQS(ch) (IN_BASE(ch) + MBOX_IRQS_OFFSET)
#define IN_IRQEN(ch) (IN_BASE(ch) + MBOX_IRQEN_OFFSET)
#define IN_IRQP(ch) (IN_BASE(ch) + MBOX_IRQP_OFFSET)

/* Bounded poll of channel ch's inbound STATUS for "RX FIFO not empty" (a word
 * arrived); stackless (register-only counter, expands inline -> no stack frame). */
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

    /* a. Clear the progress + verdict scratch and the READY rendezvous; confirm
     *    read-back 0. */
    SMC_WR32(SMU015_SMC_SCRATCH3_LOCAL, 0u);
    SMC_WR32(SMU015_SMC_SCRATCH10_LOCAL, 0u);
    SMC_WR32(SMU015_SMC_SCRATCH12_LOCAL, 0u);
    SMC_FENCE();
    if (SMC_RD32(SMU015_SMC_SCRATCH3_LOCAL) != 0u) goto fail;
    if (SMC_RD32(SMU015_SMC_SCRATCH10_LOCAL) != 0u) goto fail;
    if (SMC_RD32(SMU015_SMC_SCRATCH12_LOCAL) != 0u) goto fail;

    /* a2. Publish the SMC "up" marker on scratch2 (never cleared). The SEP polls
     *     this before its first SMC-scratch write, so READY can never race the
     *     SMC scratch init. */
    SMC_WR32(SMU015_SMC_SCRATCH2_LOCAL, SMU015_SMC_UP);
    SMC_FENCE();

    /* b. Open the SMC outbound egress filter over the mailbox region (START/END
     *    before CONFIG). No firmware read-back compare of the filter CSRs: a
     *    read-back returns hardware-fixed bits that differ from the written
     *    value. The cocotb checker verifies the filter programming via
     *    filter_ctrl_reg.field_storage. */
    SMC_WR64(SMC_FILTER_START_ADDR, SMU015_MBOX_FILTER_START);
    SMC_WR64(SMC_FILTER_END_ADDR, SMU015_MBOX_FILTER_END);
    SMC_WR64(SMC_FILTER_CONFIG_ADDR, SMU015_MBOX_FILTER_CFG);
    SMC_FENCE();

    /* c. Wait for the SEP READY (its aperture + inbound filters are up) before
     *    touching any inbound mailbox port. */
    SMC_WAIT_EQ(SMU015_SMC_SCRATCH12_LOCAL, SMU015_READY, SMU015_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* d. Arm every inbound channel's read-data IRQ (threshold 0 -> fire on any
     *    word; enable bit1); read back and confirm each port starts idle (RX
     *    empty, IRQ 0). */
    for (uint32_t ch = 0; ch < SMU015_NUM_CHANNELS; ++ch) {
        SMC_WR32(IN_RIRQT(ch), 0u);
        SMC_WR32(IN_IRQEN(ch), MBOX_IRQ_READ_MASK);
        SMC_FENCE();
        if (SMC_RD32(IN_RIRQT(ch)) != 0u) goto fail;
        if (SMC_RD32(IN_IRQEN(ch)) != MBOX_IRQ_READ_MASK) goto fail;
        if ((SMC_RD32(IN_STATUS(ch)) & MBOX_STATUS_EMPTY_MASK) == 0u) goto fail; /* RX empty */
        if (SMC_RD32(IN_IRQS(ch)) != 0u) goto fail;
        if (SMC_RD32(IN_IRQP(ch)) != 0u) goto fail;
    }

    /* e. Signal ARMED: the SEP may now start pushing channel 0. */
    SMC_WR32(SMU015_SMC_SCRATCH3_LOCAL, SMU015_PROGRESS_ARMED);
    SMC_FENCE();

    /* f. Service all eight channels strictly in order. */
    for (uint32_t ch = 0; ch < SMU015_NUM_CHANNELS; ++ch) {
        /* f1. Wait this channel's inbound RX FIFO non-empty (the SEP pushed its
         *     token). */
        SMC_WAIT_NOT_EMPTY_CH(ch, ok);
        if (!ok) goto fail;
        /* f2. The read-data-available IRQ must be latched on this port (arrival). */
        if ((SMC_RD32(IN_IRQS(ch)) & MBOX_IRQ_READ_MASK) == 0u) goto fail;
        if ((SMC_RD32(IN_IRQP(ch)) & MBOX_IRQ_READ_MASK) == 0u) goto fail;
        /* f3. Pop + verify the exact per-channel token. */
        if (SMC_RD32(IN_RDATA(ch)) != (SMU015_TOKEN_BASE | ch)) goto fail;
        /* f4. W1C the read IRQ, then read back IRQS=0 / IRQP=0 (full clear). */
        SMC_WR32(IN_IRQS(ch), SMU015_W1C_VALUE);
        SMC_FENCE();
        if (SMC_RD32(IN_IRQS(ch)) != 0u) goto fail;
        if (SMC_RD32(IN_IRQP(ch)) != 0u) goto fail;
        /* f5. Hold the port quiet across the no-refire window (well beyond
         *     64 clk_smc). */
        SMC_DELAY_ITERS(SMU015_NOREFIRE_HOLD_ITERS);
        /* f6. Publish per-channel done so the SEP advances to ch+1. */
        SMC_WR32(SMU015_SMC_SCRATCH3_LOCAL, SMU015_PROGRESS_ARMED | (ch + 1u));
        SMC_FENCE();
    }

    /* g. All eight channels consumed + cleared: publish the SMC verdict and park
     *    (named loop). */
    SMC_WR32(SMU015_SMC_SCRATCH10_LOCAL, SMU015_SMC_PASS);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_mailbox_irq_smc_pass_loop");

fail:
    SMC_WR32(SMU015_SMC_SCRATCH10_LOCAL, SMU015_SMC_FAIL);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_mailbox_irq_smc_fail_loop");
    return 0; /* unreachable */
}
