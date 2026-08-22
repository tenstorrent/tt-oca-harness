// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP outbound AXI-lite mailbox (axil_mailbox) firmware driver.
//
// The SEP system-peripheral mailbox block (hw/ip/axi_lite_mailbox_unit) exposes eight
// outbound mailboxes in the SEP-local fabric at 0x10A0_0000. Each outbound
// mailbox is a small FIFO with a threshold-based interrupt: writing data past
// the write threshold (WIRQT) latches the write-IRQ status bit, and the block
// drives outbound_interrupt_o[m] = |(IRQS & IRQEN) as an active-high level line
// (the SEP instance builds it level-triggered, IrqEdgeTrig=0/IrqActHigh=1).
//
// In hw/sys/sep/rtl/sep.sv outbound_interrupt_o feeds sep_internal_interrupts[7:0]
// (one slot per mailbox), so mailbox m -> sep_internal_interrupts[m] -> VeeR EL2
// PIC source (m + 1). The block's CSR clock is gated off at reset; ungate it via
// CLOCK_GATE_CTRL bit 2 (MAILBOX_CG) before touching any mailbox register.
//
// IRQS is write-1-to-clear. Because the IRQ is level-based on FIFO occupancy
// (usage > WIRQT), W1C alone re-asserts next cycle while the FIFO stays above
// the threshold; raise WIRQT above the current usage first, then W1C, for a
// clean and persistent deassert.

#ifndef SEP_AXIL_MAILBOX_H
#define SEP_AXIL_MAILBOX_H

#include <stdint.h>

// Outbound mailbox 0 register file (0x10A0_0000). Offsets per
// hw/ip/axi_lite_mailbox_unit.
#define SEP_AXIL_MBOX0_BASE 0x10A00000u
#define SEP_AXIL_MBOX0_WRITE_DATA (SEP_AXIL_MBOX0_BASE + 0x00u) // push word into FIFO
#define SEP_AXIL_MBOX0_STATUS (SEP_AXIL_MBOX0_BASE + 0x10u)     // RO threshold/full/empty
#define SEP_AXIL_MBOX0_WIRQT (SEP_AXIL_MBOX0_BASE + 0x20u)      // write-IRQ threshold
#define SEP_AXIL_MBOX0_RIRQT (SEP_AXIL_MBOX0_BASE + 0x28u)      // read-IRQ threshold
#define SEP_AXIL_MBOX0_IRQS (SEP_AXIL_MBOX0_BASE + 0x30u)       // IRQ status (W1C)
#define SEP_AXIL_MBOX0_IRQEN (SEP_AXIL_MBOX0_BASE + 0x38u)      // IRQ enable
#define SEP_AXIL_MBOX0_IRQP (SEP_AXIL_MBOX0_BASE + 0x40u)       // IRQ pending (RO, IRQS & IRQEN)

// IRQS / IRQEN / IRQP bit fields (axi_lite_mailbox status_q decode).
#define SEP_AXIL_MBOX_IRQ_WRITE (1u << 0) // write FIFO usage crossed WIRQT
#define SEP_AXIL_MBOX_IRQ_READ (1u << 1)  // read FIFO usage crossed RIRQT
#define SEP_AXIL_MBOX_IRQ_ERROR (1u << 2) // FIFO over/underflow error
#define SEP_AXIL_MBOX_IRQ_ALL \
    (SEP_AXIL_MBOX_IRQ_WRITE | SEP_AXIL_MBOX_IRQ_READ | SEP_AXIL_MBOX_IRQ_ERROR)

// Mailbox 0 outbound interrupt -> sep_internal_interrupts[0] -> PIC source 1.
#define SEP_AXIL_MBOX0_PIC_SRC 1u

// CLOCK_GATE_CTRL (sep_cpu_ctrl @ 0x10A3_0008): bit 2 ungates the mailbox CSR
// clock. Guarded so a TU that also pulls in sep_entropy.h keeps one definition.
#ifndef SEP_CLOCK_GATE_CTRL
#define SEP_CLOCK_GATE_CTRL 0x10A30008u
#endif
#define SEP_CLOCK_GATE_MAILBOX (1u << 2)

static inline uint32_t sep_axil_mbox_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_axil_mbox_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// Ungate the mailbox CSR clock (read-modify-write so reset gating of the other
// blocks is preserved).
static inline void sep_axil_mbox_clock_enable(void) {
    uint32_t cg = sep_axil_mbox_rd(SEP_CLOCK_GATE_CTRL);
    sep_axil_mbox_wr(SEP_CLOCK_GATE_CTRL, cg | SEP_CLOCK_GATE_MAILBOX);
}

#endif // SEP_AXIL_MAILBOX_H
