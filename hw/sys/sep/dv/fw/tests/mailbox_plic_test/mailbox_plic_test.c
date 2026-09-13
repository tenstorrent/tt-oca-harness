// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP outbound-mailbox -> PIC -> CPU interrupt-delivery firmware test (OSS port
// of the reference sep_mailbox_plic_test). The EL2 CPU arms outbound mailbox 0 to
// raise its threshold interrupt, self-triggers it by pushing a word into the
// FIFO, and proves the interrupt traverses
//
//     axil_mailbox.outbound_interrupt_o[0]
//       -> sep.sv sep_mailbox_interrupt[0] -> sep_internal_interrupts[0]
//       -> sep_interrupts[0] -> VeeR EL2 PIC source 1 -> mip.MEIP -> CPU trap
//       -> mailbox_isr
//
// all internal to bare `sep` (no testbench injection). Edge: outbound mailbox
// IRQ -> PIC -> CPU -> ISR.
//
// Checks (every failure increments errors; main() returns it and start.S turns
// 0 -> PASS magic / non-zero -> FAIL magic on the 0x8000_0000 mailbox):
//   * the ISR actually fired (WFI wakes, no poll fallback);
//   * it was claimed as PIC source 1 (meihap claim id) -- proves the exact wire,
//     not merely "some interrupt arrived";
//   * the mailbox asserted the WRITE-threshold IRQ (IRQP & IRQS write bit set
//     when the ISR captured them);
//   * full clear contract: after raising WIRQT above the FIFO usage and writing
//     1-to-clear IRQS, both IRQS and IRQP read back 0 (W1C); and
//   * no interrupt storm -- the ISR count stays put once the line is deasserted.
//
// Delta vs the reference suite:
// the reference suite sprays a candidate PIC-source set {1,2,3} and passes if ANY fires; this
// port registers ONLY source 1 and asserts the claim id == 1, so a regression of
// the mailbox->PIC wiring fails the test. the reference suite deasserts by masking IRQEN and
// only checks for no re-fire; this port additionally proves the IRQS/IRQP W1C
// readback is 0 (the RW1C contract, which applies to polled and ISR
// status paths alike).

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_axil_mailbox.h"
#include "sep_pic.h"

// VeeR EL2 meihap (external-interrupt handler address pointer): claim id is
// bits [9:2]. Matches the extraction start.S's _dummy_int_handler uses.
#define CSR_MEIHAP 0xFC8

#define MBOX_TRIGGER_WORD 0x4700CAFEu // arbitrary payload pushed to fire the IRQ
#define ISR_WAIT_ITERS 200000         // WFI spins before declaring no delivery
// Quiet window to confirm a clean deassert (no re-fire). A storm from a failed
// clear re-traps within a few cycles of mret, so a few hundred iterations is
// ample; kept small so the Verilator sim fits the regression timeout.
#define STORM_CHECK_ITERS 256

static volatile uint32_t g_isr_fired = 0;
static volatile uint32_t g_isr_count = 0;
static volatile uint32_t g_claim_id = 0;
static volatile uint32_t g_irqp_before = 0;
static volatile uint32_t g_irqs_before = 0;
static volatile uint32_t g_irqs_after = 0;
static volatile uint32_t g_irqp_after = 0;

// Outbound mailbox 0 ISR: record the claim id and the asserted IRQ state, clear
// the interrupt at the source (raise WIRQT past the FIFO usage so the level
// condition drops, then W1C IRQS), and re-read to prove the clear stuck.
void __attribute__((interrupt("machine"))) mailbox_isr(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    g_claim_id = (meihap >> 2) & 0xFF;

    g_irqp_before = sep_axil_mbox_rd(SEP_AXIL_MBOX0_IRQP);
    g_irqs_before = sep_axil_mbox_rd(SEP_AXIL_MBOX0_IRQS);

    // Raise the write threshold above the (depth-8) FIFO occupancy so
    // (usage > WIRQT) is false, then write-1-to-clear the latched IRQ status;
    // with the level removed the status stays clear.
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0xFFu);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_ALL);

    // Read the clear back BEFORE masking IRQEN, so IRQP (= IRQS & IRQEN, IRQEN
    // still fully enabled here) is an independent witness that the status truly
    // cleared -- not an artifact of masking the enable.
    g_irqs_after = sep_axil_mbox_rd(SEP_AXIL_MBOX0_IRQS);
    g_irqp_after = sep_axil_mbox_rd(SEP_AXIL_MBOX0_IRQP);

    // Now also mask IRQEN (reference suite-parity deassert belt; harmless once IRQS is 0).
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQEN, 0u);

    g_isr_count++;
    g_isr_fired = 1;
    __asm__ volatile("fence" ::: "memory");
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the 0x8000_0000 mailbox window
    sep_mbx_puts("SEP mailbox PLIC test\n");
    sep_mbx_puts("STEP filter init done; mailbox CSR clock ungate written\n");

    // CLOCK_GATE_CTRL bit 2 is not a defined field (map has only pka_cg_enable).
    // Written for sequence parity; not on the proof path.
    sep_axil_mbox_clock_enable();

    // Route outbound mailbox 0 -> PIC source 1 -> ISR. The block is built
    // level-triggered active-high, so the gateway matches (type 0, polarity 0).
    pic_register_handler(SEP_AXIL_MBOX0_PIC_SRC, mailbox_isr);
    pic_set_gateway(SEP_AXIL_MBOX0_PIC_SRC, 0, 0);
    pic_set_priority(SEP_AXIL_MBOX0_PIC_SRC, 1);
    pic_enable_source(SEP_AXIL_MBOX0_PIC_SRC);
    pic_enable_interrupts();
    sep_mbx_puts("STEP ISR registered on the mailbox PIC source and enabled\n");

    // Arm mailbox 0: clear any stale status, set WIRQT=0 so the first pushed
    // word (usage 1 > 0) raises the write IRQ, enable all IRQ sources.
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0u);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQEN, SEP_AXIL_MBOX_IRQ_ALL);
    sep_mbx_puts("STEP mailbox armed: status cleared, watermark 0, IRQs enabled\n");

    g_isr_fired = 0;
    g_isr_count = 0;
    __asm__ volatile("fence" ::: "memory");

    // Trigger: push a word -> FIFO usage 1 > WIRQT 0 -> outbound_interrupt_o[0].
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WRITE_DATA, MBOX_TRIGGER_WORD);
    sep_mbx_puts("STEP one word pushed into the mailbox queue\n");

    // Wait for the ISR. A wedged delivery path must surface as FAIL, not a
    // silent pass: there is no poll fallback.
    int timeout = ISR_WAIT_ITERS;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (g_isr_fired) {
            break;
        }
    }
    if (!g_isr_fired) {
        sep_mbx_puts("FAIL: mailbox IRQ never reached the CPU (no ISR)\n");
        return 1;
    }

    // The ISR must have been claimed as PIC source 1 (the mailbox-0 wire).
    if (g_claim_id != SEP_AXIL_MBOX0_PIC_SRC) {
        sep_mbx_puts("FAIL: wrong PIC claim id ");
        sep_mbx_puthex(g_claim_id);
        sep_mbx_putc('\n');
        errors++;
    }
    // The mailbox must have raised the WRITE-threshold IRQ.
    if (!(g_irqp_before & SEP_AXIL_MBOX_IRQ_WRITE)) {
        sep_mbx_puts("FAIL: IRQP write bit not set when ISR fired\n");
        errors++;
    }
    if (!(g_irqs_before & SEP_AXIL_MBOX_IRQ_WRITE)) {
        sep_mbx_puts("FAIL: IRQS write bit not set when ISR fired\n");
        errors++;
    }
    // W1C clear contract: status and pending must read back 0.
    if (g_irqs_after & SEP_AXIL_MBOX_IRQ_ALL) {
        sep_mbx_puts("FAIL: IRQS did not clear after W1C ");
        sep_mbx_puthex(g_irqs_after);
        sep_mbx_putc('\n');
        errors++;
    }
    if (g_irqp_after != 0) {
        sep_mbx_puts("FAIL: IRQP still pending after clear ");
        sep_mbx_puthex(g_irqp_after);
        sep_mbx_putc('\n');
        errors++;
    }

    // The handler must have run exactly once. The count is printed in the pass
    // line, so compare it here rather than leaving the printed value unchecked:
    // a DUT that re-entered the ISR between the IRQP read and the storm window
    // below would otherwise print count=2 and still pass.
    if (g_isr_count != 1u) {
        sep_mbx_puts("FAIL: ISR ran ");
        sep_mbx_puthex(g_isr_count);
        sep_mbx_puts(" times, expected exactly 1\n");
        errors++;
    }

    // No interrupt storm: once deasserted the ISR count must stay fixed.
    uint32_t count_before = g_isr_count;
    for (volatile int i = 0; i < STORM_CHECK_ITERS; i++) {
        __asm__ volatile("nop");
    }
    if (g_isr_count != count_before) {
        sep_mbx_puts("FAIL: interrupt re-fired after clear (storm)\n");
        errors++;
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: mailbox[0] IRQ -> PIC claim id ");
        sep_mbx_puthex(g_claim_id);
        sep_mbx_puts(" -> CPU ISR; IRQS/IRQP W1C->0, no storm (count=");
        sep_mbx_puthex(g_isr_count);
        sep_mbx_puts(")\n");
    }
    return errors;
}
