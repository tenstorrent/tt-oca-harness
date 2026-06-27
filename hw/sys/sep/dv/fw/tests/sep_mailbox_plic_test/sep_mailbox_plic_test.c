/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*
 * SEP Mailbox Interrupt -> PIC -> CPU Delivery Test (INT-MBOX, P1)
 *
 * Closes the check_meip / PIC->CPU delivery gap that the UVM-only IRQ
 * connectivity tests cannot reach (PIC registers live on the CPU internal bus,
 * not the AXI fabric). This is a CPU-run firmware test that proves the FULL
 * path for outbound mailbox 0:
 *
 *     axil_mailbox.outbound_interrupt_o[0]
 *       -> sep.sv sep_mailbox_interrupt[0]
 *       -> sep_internal_interrupts[0] -> sep_interrupts[0]
 *       -> VeeR EL2 PIC source -> mip.MEIP -> CPU trap -> ISR
 *
 * Unlike otbn_plic_test (which PASSES even when the ISR never fires, via an
 * INTR_STATE poll fallback), this test REQUIRES the ISR to fire. If delivery is
 * broken, it FAILS.
 *
 * Mailbox -> PIC source mapping note:
 *   After the 8-slot mailbox reallocation (hw/sep/sep.sv), the outbound mailbox
 *   vector occupies sep_internal_interrupts[0:7]; mailbox 0 is internal index 0.
 *   sep_interrupts[k] drives EL2 extintsrc_req[k+1] (bit 0 is the tied
 *   no-interrupt source), so mailbox 0 is expected at PIC source 1. To be robust
 *   to any off-by-one in the mapping, the ISR is registered on a small candidate
 *   set {1,2,3} and the actual claim id is read from meihap and logged. Delivery
 *   on ANY candidate proves the path; the logged claim id documents the true
 *   mapping (confirmed = 1 in sim).
 *
 * Requires: CPU-run (NO +SEP_SKIP_CPU_RUN).
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "interrupt.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/* Outbound mailbox 0 registers (axil_mailbox, base 0x10A0_0000) */
#define MBOX0_WRITE_DATA_ADDR   OCH_SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR
#define MBOX0_STATUS_ADDR       OCH_SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR
#define MBOX0_WIRQT_ADDR        OCH_SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR
#define MBOX0_IRQS_ADDR         OCH_SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR
#define MBOX0_IRQEN_ADDR        OCH_SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR

/* Clock-gate control: bit 3 enables the mailbox clock */
#define CLOCK_GATE_CTRL_ADDR    OCH_SEP_TOP_SEP_CPU_CTRL_CLOCK_GATE_CTRL_BASE_ADDR
#define MAILBOX_CG_MASK         SEP_CPU_CTRL__CLOCK_GATE_CTRL__MAILBOX_CG_EN_bm

/* IRQS/IRQEN: 3 status bits (write-threshold / read-threshold / error).
 * Enable + clear all three. */
#define MBOX_IRQ_ALL            0x7u

/* Candidate PIC sources covering the +/-1 mapping uncertainty for mailbox. */
static const uint32_t kMailboxPicCandidates[] = {1u, 2u, 3u};
#define NUM_CANDIDATES (sizeof(kMailboxPicCandidates) / sizeof(kMailboxPicCandidates[0]))

static volatile uint32_t g_mbox_isr_fired = 0;
static volatile uint32_t g_mbox_isr_count = 0;
static volatile uint32_t g_mbox_claimid   = 0xFFFFFFFFu;

/* Read the VeeR EL2 meihap CSR (0xFC8); claim id = (meihap >> 2) & 0xFF. */
static inline uint32_t read_claimid(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, 0xFC8" : "=r"(meihap));
    return (meihap >> 2) & 0xFFu;
}

__attribute__((interrupt("machine")))
void mailbox_isr(void) {
    g_mbox_isr_fired = 1;
    g_mbox_isr_count++;
    g_mbox_claimid = read_claimid();
    /* Single-shot: mask the IRQ first (the write-threshold status is level-held
     * by FIFO fill, so a W1C alone would immediately re-fire), then W1C status.
     * Masking IRQEN deasserts outbound_interrupt_o regardless of FIFO fill. */
    WRITE_REG(MBOX0_IRQEN_ADDR, 0x0u);
    WRITE_REG(MBOX0_IRQS_ADDR, MBOX_IRQ_ALL);
}

static void enable_mailbox_clock(void) {
    uint32_t cg = READ_REG(CLOCK_GATE_CTRL_ADDR);
    cg |= MAILBOX_CG_MASK;
    WRITE_REG(CLOCK_GATE_CTRL_ADDR, cg);
    __asm__ volatile("fence" ::: "memory");
}

int main(void) {
    int errors = 0;
    sep_outbound_filter_init();

    printf("\n");
    printf("*************************************************\n");
    printf("*  SEP Mailbox IRQ -> PIC -> CPU Delivery Test  *\n");
    printf("*************************************************\n\n");

    /* Step 1: Enable the mailbox clock (registers are otherwise inaccessible). */
    printf("[STEP 1] Enabling mailbox clock gate...\n");
    enable_mailbox_clock();

    /* Step 2: Register the ISR on all candidate PIC sources and configure them. */
    printf("[STEP 2] Registering mailbox ISR on candidate PIC sources...\n");
    for (uint32_t i = 0; i < NUM_CANDIDATES; i++) {
        uint32_t src = kMailboxPicCandidates[i];
        pic_register_handler(src, mailbox_isr);
        pic_set_gateway(src, 0, 0);   /* level-triggered, active-high */
        pic_set_priority(src, 1);
        pic_enable_source(src);
        printf("         candidate PIC source %u armed\n", src);
    }
    pic_enable_interrupts();

    /* Step 3: Arm the outbound mailbox IRQ: clear status, threshold=0, enable. */
    printf("[STEP 3] Arming outbound mailbox 0 interrupt...\n");
    WRITE_REG(MBOX0_IRQS_ADDR, MBOX_IRQ_ALL);   /* clear any stale status */
    WRITE_REG(MBOX0_WIRQT_ADDR, 0x0u);          /* interrupt when >=1 word written */
    WRITE_REG(MBOX0_IRQEN_ADDR, MBOX_IRQ_ALL);  /* enable IRQ output */
    g_mbox_isr_fired = 0;
    g_mbox_isr_count = 0;

    /* Step 4: Trigger - write a word into the outbound mailbox. */
    printf("[STEP 4] Writing outbound mailbox to raise the interrupt...\n");
    WRITE_REG(MBOX0_WRITE_DATA_ADDR, 0x4700CAFEu);

    /* Step 5: Wait for the ISR (real delivery - no poll fallback). */
    printf("[STEP 5] Waiting for CPU trap / ISR...\n");
    for (volatile int i = 0; i < 200000 && !g_mbox_isr_fired; ++i);

    if (!g_mbox_isr_fired) {
        printf("FAIL: mailbox ISR never fired -- sep_interrupts[0] -> PIC -> CPU "
               "delivery is BROKEN\n");
        test_fail(1);
        while (1) { __asm__("wfi"); }
    }
    printf("[STEP 5] ISR fired (count=%u) at PIC claim id %u -- delivery confirmed\n",
           g_mbox_isr_count, g_mbox_claimid);

    /* Step 6: Confirm the interrupt stopped (deasserted) - no ongoing storm. The
     * ISR masked IRQEN, so outbound_interrupt_o drops even though the IRQS
     * write-threshold bit stays level-held by FIFO fill. A level interrupt can
     * legitimately double-take before the mask propagates, so we don't require
     * exactly one entry - only that the count has STOPPED growing. */
    printf("[STEP 6] Verifying interrupt deasserted (no ongoing storm)...\n");
    uint32_t count_before = g_mbox_isr_count;
    for (volatile int i = 0; i < 40000; ++i);
    uint32_t count_after = g_mbox_isr_count;
    if (count_after != count_before) {
        printf("ERROR: ISR still firing (count %u -> %u) -- interrupt not "
               "deasserted / storm\n", count_before, count_after);
        errors++;
    } else {
        printf("[STEP 6] interrupt deasserted (stable at count=%u)\n", count_after);
    }

    printf("\n========================================\n");
    printf("INT-MBOX: Mailbox IRQ -> PIC -> CPU\n");
    printf("  ISR fired:  YES (count=%u)\n", g_mbox_isr_count);
    printf("  Claim id:   %u (expected 1 for sep_internal_interrupts[0])\n",
           g_mbox_claimid);
    printf("  Errors:     %d\n", errors);
    printf("========================================\n");

    if (errors == 0) {
        printf("PASS: mailbox PIC->CPU delivery test completed\n");
        test_pass(0);
    } else {
        printf("FAIL: %d errors\n", errors);
        test_fail(1);
    }

    while (1) { __asm__("wfi"); }
}
