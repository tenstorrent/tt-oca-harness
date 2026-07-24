// SPDX-License-Identifier: Apache-2.0
//
// VeeR EL2 PIC (programmable interrupt controller) firmware driver for the SEP
// OSS tests. Header-only (static inline), self-contained: the PIC register
// addresses are SEP fabric facts (no generated-header dependency), matching
// och_sep_top_reg / el2_pic.rdl.
//
// VeeR EL2 is built with fast_interrupt_redirect: on an external interrupt the
// hardware reads the handler address from the meivt-based vector table and
// jumps straight to it. start.S sets meivt and pre-fills the 256-entry table
// (in DCCM) with a dummy handler; pic_register_handler() overrides one entry.
// Handlers must be declared __attribute__((interrupt("machine"))).

#ifndef SEP_PIC_H
#define SEP_PIC_H

#include <stdint.h>

// Per-source PIC register file bases (entry for source 1; source N is base +
// (N-1)*4). VeeR EL2 source 0 is the tied "no interrupt" source.
#define SEP_PIC_MEIPL_0    0xC0080004u  // priority (4-bit), 0 disables the source
#define SEP_PIC_MEIE_0     0xC0082004u  // per-source enable
#define SEP_PIC_MEIGWCTRL_0 0xC0084004u // gateway: [0]=polarity, [1]=irq_type

// The vector table base symbol from the linker script (1024-byte aligned, 256
// 32-bit entries in DCCM).
extern char INTVEC_BASE[];

typedef void (*pic_handler_t)(void);

static inline void _pic_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// Install a handler for an interrupt source (vector-table entry source_id).
static inline void pic_register_handler(uint32_t source_id, pic_handler_t handler) {
    volatile uint32_t *vectbl = (volatile uint32_t *)INTVEC_BASE;
    vectbl[source_id] = (uint32_t)handler;
    __asm__ volatile("fence" ::: "memory");
}

// Priority 0 disables; 1..15 enable at that level.
static inline void pic_set_priority(uint32_t source_id, uint32_t priority) {
    _pic_wr(SEP_PIC_MEIPL_0 + (source_id - 1) * 4, priority & 0xF);
}

// type: 0=level, 1=edge. polarity: 0=active-high, 1=active-low.
static inline void pic_set_gateway(uint32_t source_id, uint32_t type, uint32_t polarity) {
    _pic_wr(SEP_PIC_MEIGWCTRL_0 + (source_id - 1) * 4,
            (polarity & 0x1) | ((type & 0x1) << 1));
}

static inline void pic_enable_source(uint32_t source_id) {
    _pic_wr(SEP_PIC_MEIE_0 + (source_id - 1) * 4, 1);
}

static inline void pic_disable_source(uint32_t source_id) {
    _pic_wr(SEP_PIC_MEIE_0 + (source_id - 1) * 4, 0);
}

// Drop the PIC priority threshold/current level to 0 and enable machine
// external interrupts (mie.meie) + global interrupts (mstatus.mie).
static inline void pic_enable_interrupts(void) {
    __asm__ volatile("csrwi 0xBC9, 0");  // meipt = 0 (priority threshold)
    __asm__ volatile("csrwi 0xBCC, 0");  // meicurpl = 0 (current priority level)
    __asm__ volatile("csrs mie, %0" ::"r"(1u << 11));      // mie.meie
    __asm__ volatile("csrs mstatus, %0" ::"r"(1u << 3));   // mstatus.mie
}

static inline void pic_disable_interrupts(void) {
    __asm__ volatile("csrc mstatus, %0" ::"r"(1u << 3));
}

#endif  // SEP_PIC_H
