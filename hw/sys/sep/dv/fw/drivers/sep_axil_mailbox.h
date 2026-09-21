// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP AXI-lite mailbox (axil_mailbox) firmware driver.
//
// The SEP system-peripheral mailbox block (hw/ip/axi_lite_mailbox_unit) exposes
// eight mailbox pairs. Addresses and IRQ field masks come from generated
// sep_addr.h / axil_mailbox_sep_wrap.h (via sep.h).
//
// These defines target the inbound aperture, because in hw/sys/sep/rtl/sep.sv
// only inbound_interrupt_o reaches sep_internal_interrupts[7:0]; outbound
// leaves the block on smc_mailbox_interrupt_o. A write to inbound WRITE_DATA
// is therefore what notifies the SEP CPU. interrupts.adoc PIC sources 1-8 are
// Mailbox interrupt 0-7, so channel ch drives PIC source (ch + 1). CLOCK_GATE_CTRL in this map implements only
// pka_cg_enable (bit 0). Bit 2 is written for sequence parity; it is not a
// defined mailbox-clock field and is not on the proof path.
//
// IRQS is write-1-to-clear. Because the IRQ is level-based on FIFO occupancy
// (usage > WIRQT), W1C alone re-asserts next cycle while the FIFO stays above
// the threshold; raise WIRQT above the current usage first, then W1C, for a
// clean and persistent deassert.

#ifndef SEP_AXIL_MAILBOX_H
#define SEP_AXIL_MAILBOX_H

#include <stdint.h>

#include "sep.h"

#define SEP_AXIL_MBOX0_BASE SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR
#define SEP_AXIL_MBOX0_WRITE_DATA SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR
#define SEP_AXIL_MBOX0_STATUS SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_STATUS_BASE_ADDR
#define SEP_AXIL_MBOX0_WIRQT SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WIRQT_BASE_ADDR
#define SEP_AXIL_MBOX0_RIRQT SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_RIRQT_BASE_ADDR
#define SEP_AXIL_MBOX0_IRQS SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_IRQS_BASE_ADDR
#define SEP_AXIL_MBOX0_IRQEN SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_IRQEN_BASE_ADDR
#define SEP_AXIL_MBOX0_IRQP SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_IRQP_BASE_ADDR

#define SEP_AXIL_MBOX_IRQ_WRITE AXIL_MAILBOX__IRQS__WTIRQ_bm
#define SEP_AXIL_MBOX_IRQ_READ AXIL_MAILBOX__IRQS__RTIRQ_bm
#define SEP_AXIL_MBOX_IRQ_ERROR AXIL_MAILBOX__IRQS__EIRQ_bm
#define SEP_AXIL_MBOX_IRQ_ALL \
    (SEP_AXIL_MBOX_IRQ_WRITE | SEP_AXIL_MBOX_IRQ_READ | SEP_AXIL_MBOX_IRQ_ERROR)

// Mailbox 0 inbound interrupt -> PIC source 1 (interrupts.adoc).
#define SEP_AXIL_MBOX0_PIC_SRC 1u

// Eight channels, stride from generated mailbox 0 vs 1 WRITE_DATA.
// Channel ch drives PIC source (ch + 1) (interrupts.adoc Mailbox interrupt ch).
#define SEP_AXIL_MBOX_N 8u
#define SEP_AXIL_MBOX_STRIDE                                                         \
    (SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_1_WRITE_DATA_BASE_ADDR -              \
     SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR)

// The paired outbound aperture. Its interrupt leaves the block on
// smc_mailbox_interrupt_o, so a push here must NOT reach the SEP CPU PIC --
// which is what the direction leg of sep_mailbox_plic_test asserts.
#define SEP_AXIL_MBOX0_OUT_WRITE_DATA SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR
#define SEP_AXIL_MBOX0_OUT_WIRQT SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR
#define SEP_AXIL_MBOX0_OUT_IRQS SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR
#define SEP_AXIL_MBOX0_OUT_IRQEN SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR

static inline uint32_t sep_axil_mbox_ch(uint32_t ch, uint32_t mbox0_addr) {
    return mbox0_addr + ch * SEP_AXIL_MBOX_STRIDE;
}

#ifndef SEP_CLOCK_GATE_CTRL
#define SEP_CLOCK_GATE_CTRL SEP_TOP_SEP_CPU_CTRL_CLOCK_GATE_CTRL_BASE_ADDR
#endif
// Not a defined CLOCK_GATE_CTRL field in this map (only pka_cg_enable exists).
#define SEP_CLOCK_GATE_MAILBOX (1u << 2)

static inline uint32_t sep_axil_mbox_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void sep_axil_mbox_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// Write CLOCK_GATE_CTRL bit 2 (not a defined field). Read-modify-write so
// other implemented bits stay as they were.
static inline void sep_axil_mbox_clock_enable(void) {
    uint32_t cg = sep_axil_mbox_rd(SEP_CLOCK_GATE_CTRL);
    sep_axil_mbox_wr(SEP_CLOCK_GATE_CTRL, cg | SEP_CLOCK_GATE_MAILBOX);
}

#endif // SEP_AXIL_MAILBOX_H
