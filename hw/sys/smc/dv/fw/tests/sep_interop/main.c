/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "sep_interop_protocol.h"

/*
 * SEP Interop - SMC side of the SEP/SMC mailbox handshake
 *
 * Verifies that the SMC and the live SEP CPU complete a token, response, acknowledge and
 * completion exchange over the SEP mailbox pair through real MMIO only, and that the SMC-side
 * mailbox interrupt status and pending state clear after each pop.
 *
 * The SEP-driven bring-up does not initialise the SMC SRAM stack, so main() is stackless:
 * it makes no function calls and uses only the smc_stackless_test.h macros. Any stack
 * frame in main() hangs the core.
 */
SMC_STACKLESS_ENTRY(sep_interop_entry)

/* SMC-local scratch registers used by the handshake. */
#define SMC_SCRATCH0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8)   /* status / verdict        */
#define SMC_SCRATCH2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8)   /* SMC "up" marker -> SEP  */
#define SMC_SCRATCH12 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 12 * 8) /* SEP READY rendezvous    */

/* SMC outbound filter entry 0 opens the mailbox window. Its CSRs are 64-bit, and each RV64
 * store is a single transaction. */
#define SMC_OUTBOUND_FILTER_BASE 0x00000000C0016000ULL
#define SMC_FILTER_CONFIG_OFFSET 0x00ULL
#define SMC_FILTER_START_OFFSET 0x08ULL
#define SMC_FILTER_END_OFFSET 0x10ULL
#define SMC_MBOX_WINDOW_START 0x0000000010A00800ULL /* SMC-facing mailbox port */
#define SMC_MBOX_WINDOW_END 0x0000000010A00FFFULL
/* Read/write enabled with bursts disallowed, so the sub-4 KB window end is stored exactly. */
#define SMC_MBOX_FILTER_CONFIG 0x0000000100030013ULL

/* SMC-facing mailbox port registers. */
#define SMC_MBOX_WRITE_DATA (SMC_INBOUND_MBOX_BASE + MBOX_WRITE_DATA_OFFSET)
#define SMC_MBOX_READ_DATA (SMC_INBOUND_MBOX_BASE + MBOX_READ_DATA_OFFSET)
#define SMC_MBOX_STATUS (SMC_INBOUND_MBOX_BASE + MBOX_STATUS_OFFSET)
#define SMC_MBOX_RIRQT (SMC_INBOUND_MBOX_BASE + MBOX_RIRQT_OFFSET)
#define SMC_MBOX_IRQS (SMC_INBOUND_MBOX_BASE + MBOX_IRQS_OFFSET)
#define SMC_MBOX_IRQEN (SMC_INBOUND_MBOX_BASE + MBOX_IRQEN_OFFSET)
#define SMC_MBOX_IRQP (SMC_INBOUND_MBOX_BASE + MBOX_IRQP_OFFSET)

/* Bounded wait for a word to arrive on the SMC-facing port; stackless, like SMC_WAIT_EQ. */
#define SMC_WAIT_NOT_EMPTY(status_addr, limit, okvar) \
    do { \
        okvar = 0; \
        for (uint32_t _i = 0; _i < (uint32_t)(limit); ++_i) { \
            if ((SMC_RD32(status_addr) & MBOX_STATUS_EMPTY_MASK) == 0u) { \
                okvar = 1; \
                break; \
            } \
        } \
    } while (0)

int main(void) {
    uint32_t ok;

    /* a. Clear the SEP READY rendezvous scratch and confirm it reads back 0. */
    SMC_WR32(SMC_SCRATCH12, 0u);
    SMC_FENCE();
    if (SMC_RD32(SMC_SCRATCH12) != 0u) goto fail;

    /* a2. Publish the SMC "up" marker, which is never cleared. The SEP polls it before its first
     *     write to SMC scratch, so READY cannot race the SMC scratch clear. */
    SMC_WR32(SMC_SCRATCH2, SEP_INTEROP_SMC_UP);
    SMC_FENCE();

    /* b. Open the SMC outbound filter over the mailbox window. The window bounds go in before
     *    the configuration so the filter enables atomically. The filter CSRs are not read back:
     *    a read returns hardware-fixed bits that differ from the written value. */
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + SMC_FILTER_START_OFFSET, SMC_MBOX_WINDOW_START);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + SMC_FILTER_END_OFFSET, SMC_MBOX_WINDOW_END);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + SMC_FILTER_CONFIG_OFFSET, SMC_MBOX_FILTER_CONFIG);
    SMC_FENCE();

    /* c. Arm the read interrupt to fire on any arriving word, read the setup back, and check
     *    that the port starts idle: receive FIFO empty and no interrupt. */
    SMC_WR32(SMC_MBOX_RIRQT, 0u);
    SMC_WR32(SMC_MBOX_IRQEN, MBOX_IRQ_READ_MASK);
    SMC_FENCE();
    if (SMC_RD32(SMC_MBOX_RIRQT) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQEN) != MBOX_IRQ_READ_MASK) goto fail;
    if ((SMC_RD32(SMC_MBOX_STATUS) & MBOX_STATUS_EMPTY_MASK) == 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQS) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQP) != 0u) goto fail;

    /* d. Wait for the SEP to publish READY into scratch12 (its mailbox side is up). */
    SMC_WAIT_EQ(SMC_SCRATCH12, SEP_INTEROP_READY, SEP_INTEROP_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* e. Send the opening token to the SEP. */
    SMC_WR32(SMC_MBOX_WRITE_DATA, SEP_INTEROP_TOKEN);
    SMC_FENCE();

    /* f. Wait for the SEP response, pop it and check the exact value, then clear the interrupt
     *    and check that status and pending both drop. */
    SMC_WAIT_NOT_EMPTY(SMC_MBOX_STATUS, SEP_INTEROP_POLL_LIMIT, ok);
    if (!ok) goto fail;
    if (SMC_RD32(SMC_MBOX_READ_DATA) != SEP_INTEROP_RESPONSE) goto fail;
    /* Clear every status bit: the write-threshold bit latches as a side effect of the push. */
    SMC_WR32(SMC_MBOX_IRQS, MBOX_IRQ_ALL);
    SMC_FENCE();
    if (SMC_RD32(SMC_MBOX_IRQS) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQP) != 0u) goto fail;

    /* g. Acknowledge the response. */
    SMC_WR32(SMC_MBOX_WRITE_DATA, SEP_INTEROP_ACK);
    SMC_FENCE();

    /* h. Wait for the SEP completion word, pop it and check it, then clear the interrupt. */
    SMC_WAIT_NOT_EMPTY(SMC_MBOX_STATUS, SEP_INTEROP_POLL_LIMIT, ok);
    if (!ok) goto fail;
    if (SMC_RD32(SMC_MBOX_READ_DATA) != SEP_INTEROP_SEP_PASS) goto fail;
    SMC_WR32(SMC_MBOX_IRQS, MBOX_IRQ_ALL);
    SMC_FENCE();
    if (SMC_RD32(SMC_MBOX_IRQS) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQP) != 0u) goto fail;

    /* i. Report the pass verdict and park. */
    SMC_WR32(SMC_SCRATCH0, SEP_INTEROP_TEST_PASS);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");

fail:
    SMC_WR32(SMC_SCRATCH0, SEP_INTEROP_TEST_FAIL);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");
}
