/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h" /* common: SMC_STACKLESS_ENTRY, SMC_WR32/RD32, SMC_WAIT_EQ */
#include "sep_interop_protocol.h"

/*
 * SEP_SMU_002  sep_interop  --  SMC (producer) firmware.
 *
 * Real SMC firmware runs a bidirectional mailbox handshake against the live SEP CPU over the
 * SEP AXI-lite mailbox pair. The SMC drives the SMC-facing port (INBOUND_MAILBOX_0 @
 * 0x10A00800); the SEP drives the SEP-local port (OUTBOUND_MAILBOX_0 @ 0x10A00000). No
 * force/deposit: the SMC opens its OWN outbound egress filter over the mailbox window,
 * programs the mailbox read-data IRQ, waits for the SEP READY rendezvous in scratch12, then
 * exchanges TOKEN -> RESPONSE -> ACK -> SEP_PASS, write-1-to-clearing the mailbox read IRQ
 * (and confirming IRQ status/pending drop to 0) after each pop.
 *
 * STACKLESS (smc_stackless_test.h): the SMU cocotb / SEP-driven boot does not initialise the
 * SMC SRAM stack, so main() makes no function calls and uses only the SMC_* absolute-MMIO/poll
 * macros; any `add sp,sp,-N` in the entry hangs the core.
 */
SMC_STACKLESS_ENTRY(sep_interop_entry)

/* SMC-local scratch absolute addresses (CPU_CTRL array, 8-byte stride, base 0xC0039080). */
#define SMC_SCRATCH0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8)   /* status / verdict        */
#define SMC_SCRATCH2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8)   /* SMC "up" marker -> SEP  */
#define SMC_SCRATCH12 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 12 * 8) /* SEP READY rendezvous    */

/* SMC outbound egress filter 0 (opens the mailbox window; 64-bit CSRs). SMC is RV64 so the
 * 64-bit MMIO stores are single transactions here. */
#define SMC_OUTBOUND_FILTER_BASE 0x00000000C0016000ULL /* SMC_OUTBOUND_FILTER_CTRL_0        */
#define SMC_FILTER_CONFIG_OFFSET 0x00ULL
#define SMC_FILTER_START_OFFSET 0x08ULL
#define SMC_FILTER_END_OFFSET 0x10ULL
#define SMC_MBOX_WINDOW_START 0x0000000010A00800ULL /* SMC-facing mailbox port          */
#define SMC_MBOX_WINDOW_END 0x0000000010A00FFFULL
#define SMC_MBOX_FILTER_CONFIG \
    0x0000000100030013ULL /* read/write/enable/src_id=3; allow_burst=0 \
                             so the sub-4KB window END stores EXACTLY \
                             (allow_burst=1 rounds END to 0x..FFF) */

/* SMC-facing mailbox port (INBOUND_MAILBOX_0) absolute register addresses. */
#define SMC_MBOX_WRITE_DATA (SMC_INBOUND_MBOX_BASE + MBOX_WRITE_DATA_OFFSET) /* 0x10A00800 */
#define SMC_MBOX_READ_DATA (SMC_INBOUND_MBOX_BASE + MBOX_READ_DATA_OFFSET)   /* 0x10A00808 */
#define SMC_MBOX_STATUS (SMC_INBOUND_MBOX_BASE + MBOX_STATUS_OFFSET)         /* 0x10A00810 */
#define SMC_MBOX_RIRQT (SMC_INBOUND_MBOX_BASE + MBOX_RIRQT_OFFSET)           /* 0x10A00828 */
#define SMC_MBOX_IRQS (SMC_INBOUND_MBOX_BASE + MBOX_IRQS_OFFSET)             /* 0x10A00830 */
#define SMC_MBOX_IRQEN (SMC_INBOUND_MBOX_BASE + MBOX_IRQEN_OFFSET)           /* 0x10A00838 */
#define SMC_MBOX_IRQP (SMC_INBOUND_MBOX_BASE + MBOX_IRQP_OFFSET)             /* 0x10A00840 */

/* Bounded poll of the SMC-facing mailbox STATUS for "RX FIFO not empty" (a word arrived);
 * mirrors SMC_WAIT_EQ (register-only counter -> keeps main() stackless). */
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

    /* a2. Publish the SMC "up" marker on scratch2 now that the SMC is past its own scratch init
     *     (scratch12 cleared/read-back-0 above; scratch2 is written once here and never cleared).
     *     The SEP polls this BEFORE its first SMC-scratch write, so READY can never race the SMC
     *     scratch clear -- mirrors SEP_SMU_004 publishing INIT_RELEASE_OK before the SEP writes. */
    SMC_WR32(SMC_SCRATCH2, SEP_INTEROP_SMC_UP);
    SMC_FENCE();

    /* b. Open the SMC outbound egress filter over the mailbox window (START/END before CONFIG
     *    so it enables atomically). No firmware read-back compare of the filter CSRs: a
     *    read-back returns hardware-fixed bits (RO data_bus_width, reserved bit[32],
     *    allow_burst-rounded START/END) that differ from the written value. The cocotb checker
     *    (CHK-SETUP) verifies the filter programming via filter_ctrl_reg.field_storage. */
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + SMC_FILTER_START_OFFSET, SMC_MBOX_WINDOW_START);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + SMC_FILTER_END_OFFSET, SMC_MBOX_WINDOW_END);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + SMC_FILTER_CONFIG_OFFSET, SMC_MBOX_FILTER_CONFIG);
    SMC_FENCE();

    /* c. Arm the SMC-facing mailbox read-data IRQ (threshold 0 -> fire on any word; enable
     *    bit1); read back, and confirm the port starts idle -- RX FIFO empty, no IRQ. */
    SMC_WR32(SMC_MBOX_RIRQT, 0u);
    SMC_WR32(SMC_MBOX_IRQEN, MBOX_IRQ_READ_MASK);
    SMC_FENCE();
    if (SMC_RD32(SMC_MBOX_RIRQT) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQEN) != MBOX_IRQ_READ_MASK) goto fail;
    if ((SMC_RD32(SMC_MBOX_STATUS) & MBOX_STATUS_EMPTY_MASK) == 0u) goto fail; /* RX empty */
    if (SMC_RD32(SMC_MBOX_IRQS) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQP) != 0u) goto fail;

    /* d. Wait for the SEP to publish READY into scratch12 (its mailbox side is up). */
    SMC_WAIT_EQ(SMC_SCRATCH12, SEP_INTEROP_READY, SEP_INTEROP_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* e. Send the opening token to the SEP. */
    SMC_WR32(SMC_MBOX_WRITE_DATA, SEP_INTEROP_TOKEN);
    SMC_FENCE();

    /* f. Wait for the SEP RESPONSE, pop it, verify the EXACT literal (not ~TOKEN), then W1C the
     *    mailbox read IRQ and confirm IRQ status/pending clear. */
    SMC_WAIT_NOT_EMPTY(SMC_MBOX_STATUS, SEP_INTEROP_POLL_LIMIT, ok);
    if (!ok) goto fail;
    if (SMC_RD32(SMC_MBOX_READ_DATA) != SEP_INTEROP_RESPONSE) goto fail;
    SMC_WR32(SMC_MBOX_IRQS, MBOX_IRQ_ALL); /* W1C ALL: read + sticky write-threshold bit */
    SMC_FENCE();
    if (SMC_RD32(SMC_MBOX_IRQS) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQP) != 0u) goto fail;

    /* g. Acknowledge the response. */
    SMC_WR32(SMC_MBOX_WRITE_DATA, SEP_INTEROP_ACK);
    SMC_FENCE();

    /* h. Wait for the SEP completion word, pop it, verify, W1C, confirm clear. */
    SMC_WAIT_NOT_EMPTY(SMC_MBOX_STATUS, SEP_INTEROP_POLL_LIMIT, ok);
    if (!ok) goto fail;
    if (SMC_RD32(SMC_MBOX_READ_DATA) != SEP_INTEROP_SEP_PASS) goto fail;
    SMC_WR32(SMC_MBOX_IRQS, MBOX_IRQ_ALL); /* W1C ALL: read + sticky write-threshold bit */
    SMC_FENCE();
    if (SMC_RD32(SMC_MBOX_IRQS) != 0u) goto fail;
    if (SMC_RD32(SMC_MBOX_IRQP) != 0u) goto fail;

    /* i. Whole-test pass: publish TEST_PASS to scratch0 and park. */
    SMC_WR32(SMC_SCRATCH0, SEP_INTEROP_TEST_PASS);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");

fail:
    SMC_WR32(SMC_SCRATCH0, SEP_INTEROP_TEST_FAIL);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");
}
