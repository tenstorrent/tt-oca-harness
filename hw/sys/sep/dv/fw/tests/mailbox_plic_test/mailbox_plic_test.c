/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP inbound-mailbox -> PIC -> CPU interrupt-delivery firmware test. For each
 * of the eight inbound mailbox channels, the CPU pushes one word into the
 * channel FIFO to raise its write-threshold interrupt, with no testbench
 * injection, and checks that:
 *   * the ISR fires on a WFI wake, claimed as that channel's own PIC source,
 *     so a miswired source fails rather than any interrupt passing;
 *   * the mailbox shows the write-threshold interrupt latched and pending;
 *   * after the threshold is raised above the FIFO usage and the status is
 *     written 1-to-clear, status and pending both read back clear while the
 *     enable is still set; and
 *   * the ISR runs exactly once and does not re-fire.
 *
 * A last leg pushes one word into the outbound channel-0 aperture with every
 * mailbox PIC source enabled and checks that no interrupt reaches the CPU.
 *
 * main() returns the error count; crt0.s turns 0 into the PASS magic and any
 * other value into the FAIL magic.
 */

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_axil_mailbox.h"
#include "sep_pic.h"

// VeeR EL2 external-interrupt handler address pointer, which carries the claim
// id; decoded the same way as crt0.s's _dummy_int_handler.
#define CSR_MEIHAP 0xFC8

#define MBOX_TRIGGER_WORD 0x4700CAFEu // arbitrary payload pushed to fire the IRQ
#define ISR_WAIT_ITERS 200000         // WFI spins before declaring no delivery
// Quiet window for the direction leg. Long enough that a live outbound->PIC
// path would have delivered: the inbound legs above wake on the first WFI.
#define OUTBOUND_QUIET_ITERS 20000
// Quiet window to confirm a clean deassert (no re-fire). A storm from a failed
// clear re-traps within a few cycles of mret, so a few hundred iterations is
// ample; kept small so the Verilator sim fits the regression timeout.
#define STORM_CHECK_ITERS 256

static volatile uint32_t g_ch = 0;
static volatile uint32_t g_isr_fired = 0;
static volatile uint32_t g_isr_count = 0;
static volatile uint32_t g_claim_id = 0;
static volatile uint32_t g_irqp_before = 0;
static volatile uint32_t g_irqs_before = 0;
static volatile uint32_t g_irqs_after = 0;
static volatile uint32_t g_irqp_after = 0;

// Inbound mailbox ISR: record the claim id and interrupt state, clear the
// interrupt at the source, and read the clear back.
void __attribute__((interrupt("machine"))) mailbox_isr(void) {
    uint32_t ch = g_ch;
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    g_claim_id = (meihap >> 2) & 0xFF;

    g_irqp_before = sep_axil_mbox_rd(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQP));
    g_irqs_before = sep_axil_mbox_rd(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQS));

    // Raise the write threshold above the FIFO occupancy so the level condition
    // drops, then clear the latched status; with the level gone it stays clear.
    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_WIRQT), 0xFFu);
    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQS), SEP_AXIL_MBOX_IRQ_ALL);

    // Read the clear back before masking the enable, so the pending state is an
    // independent witness that the status cleared, not an artifact of the mask.
    g_irqs_after = sep_axil_mbox_rd(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQS));
    g_irqp_after = sep_axil_mbox_rd(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQP));

    // Also mask the enable; harmless once the status is clear.
    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQEN), 0u);

    g_isr_count++;
    g_isr_fired = 1;
    __asm__ volatile("fence" ::: "memory");
}

static int run_channel(uint32_t ch) {
    int errors = 0;
    uint32_t pic_src = ch + 1u;

    g_ch = ch;
    g_isr_fired = 0;
    g_isr_count = 0;
    g_claim_id = 0;
    g_irqp_before = 0;
    g_irqs_before = 0;
    g_irqs_after = 0;
    g_irqp_after = 0;
    __asm__ volatile("fence" ::: "memory");

    pic_register_handler(pic_src, mailbox_isr);
    pic_set_gateway(pic_src, 0, 0);
    pic_set_priority(pic_src, 1);
    pic_enable_source(pic_src);

    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQS), SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_WIRQT), 0u);
    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_IRQEN), SEP_AXIL_MBOX_IRQ_ALL);

    sep_axil_mbox_wr(sep_axil_mbox_ch(ch, SEP_AXIL_MBOX0_WRITE_DATA), MBOX_TRIGGER_WORD);

    int timeout = ISR_WAIT_ITERS;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (g_isr_fired) {
            break;
        }
    }
    if (!g_isr_fired) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] IRQ never reached the CPU (no ISR)\n");
        return 1;
    }

    if (g_claim_id != pic_src) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] wrong PIC claim id ");
        sep_mbx_puthex(g_claim_id);
        sep_mbx_putc('\n');
        errors++;
    }
    if (!(g_irqp_before & SEP_AXIL_MBOX_IRQ_WRITE)) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] IRQP write bit not set when ISR fired\n");
        errors++;
    }
    if (!(g_irqs_before & SEP_AXIL_MBOX_IRQ_WRITE)) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] IRQS write bit not set when ISR fired\n");
        errors++;
    }
    if ((g_irqs_after & SEP_AXIL_MBOX_IRQ_ALL) || g_irqp_after != 0) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] IRQS/IRQP did not clear after W1C irqs=");
        sep_mbx_puthex(g_irqs_after);
        sep_mbx_puts(" irqp=");
        sep_mbx_puthex(g_irqp_after);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-RW1C PASS: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] IRQS/IRQP W1C->0 while IRQEN still set\n");
    }
    if (g_isr_count != 1u) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] ISR ran ");
        sep_mbx_puthex(g_isr_count);
        sep_mbx_puts(" times, expected exactly 1\n");
        errors++;
    }

    uint32_t count_before = g_isr_count;
    for (volatile int i = 0; i < STORM_CHECK_ITERS; i++) {
        __asm__ volatile("nop");
    }
    if (g_isr_count != count_before) {
        sep_mbx_puts("FAIL: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] interrupt re-fired after clear (storm)\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-NOSTORM PASS: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] ISR ran once and did not re-fire\n");
    }

    if (errors == 0) {
        sep_mbx_puts("CHK-DELIVER PASS: mailbox[");
        sep_mbx_puthex(ch);
        sep_mbx_puts("] IRQ -> PIC claim id ");
        sep_mbx_puthex(g_claim_id);
        sep_mbx_puts(" -> CPU ISR\n");
    }

    pic_disable_source(pic_src);
    return errors;
}

// Direction leg. The mailbox PIC sources carry only the inbound channel
// interrupts (hw/sys/sep/doc/interrupts.adoc); the interrupts toward the SMC
// leave on smc_mailbox_interrupt_o (hw/sys/sep/doc/port_table.adoc). Arm the
// outbound channel-0 aperture with every mailbox PIC source enabled and push one
// word; the ISR must stay silent. The entry is left pending on purpose so the
// testbench can see the outbound interrupt asserted at end of run.
static int run_outbound_no_cpu_delivery(void) {
    uint32_t pic_src = SEP_AXIL_MBOX0_PIC_SRC;

    g_ch = 0;
    g_isr_fired = 0;
    g_isr_count = 0;
    __asm__ volatile("fence" ::: "memory");

    // Every mailbox source, not just source 1: an outbound IRQ miswired onto a
    // neighbouring PIC source would otherwise be invisible here.
    for (uint32_t src = pic_src; src < pic_src + SEP_AXIL_MBOX_N; src++) {
        pic_register_handler(src, mailbox_isr);
        pic_set_gateway(src, 0, 0);
        pic_set_priority(src, 1);
        pic_enable_source(src);
    }

    sep_axil_mbox_wr(SEP_AXIL_MBOX0_OUT_IRQS, SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_OUT_WIRQT, 0u);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_OUT_IRQEN, SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_OUT_WRITE_DATA, MBOX_TRIGGER_WORD);

    // Spin, not WFI: nothing should wake us, and WFI with no pending interrupt
    // would stall the core instead of letting the window expire.
    for (volatile int i = 0; i < OUTBOUND_QUIET_ITERS; i++) {
        __asm__ volatile("" ::: "memory");
    }

    for (uint32_t src = pic_src; src < pic_src + SEP_AXIL_MBOX_N; src++) {
        pic_disable_source(src);
    }

    if (g_isr_fired) {
        sep_mbx_puts("FAIL: an outbound-aperture push reached the CPU PIC "
                     "(claim id taken); outbound must leave on "
                     "smc_mailbox_interrupt_o\n");
        return 1;
    }
    sep_mbx_puts("CHK-DIRECTION PASS: outbound push raised none of the eight "
                 "mailbox PIC sources\n");
    return 0;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the mailbox window
    sep_mbx_puts("SEP mailbox PLIC test\n");
    sep_mbx_puts("STEP filter init done; mailbox CSR clock ungate written\n");

    // This clock-enable write targets no defined register field; it is not on
    // the checked path.
    sep_axil_mbox_clock_enable();

    pic_enable_interrupts();
    sep_mbx_puts("STEP ISR registered per inbound mailbox PIC source\n");

    for (uint32_t ch = 0; ch < SEP_AXIL_MBOX_N; ch++) {
        errors += run_channel(ch);
        if (errors) {
            return errors;
        }
    }

    // Direction leg last: the entry it pushes stays in the outbound FIFO, and
    // the paired inbound port would see it as read-data-available, which would
    // make a later inbound channel-0 leg fire on the read threshold instead of
    // the write one.
    errors += run_outbound_no_cpu_delivery();
    if (errors) {
        return errors;
    }

    sep_mbx_puts("PASS: mailbox[0..7] IRQ -> PIC claim id == ch+1 -> CPU ISR; "
                 "IRQS/IRQP W1C->0, no storm; outbound push off the CPU PIC\n");
    return 0;
}
