// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VeeR EL2 PIC (programmable interrupt controller) firmware driver for the SEP
// OSS tests. Header-only (static inline). PIC register addresses come from
// generated sep_addr.h (via sep.h).
//
// VeeR EL2 is built with fast_interrupt_redirect: on an external interrupt the
// hardware reads the handler address from the meivt-based vector table and
// jumps straight to it. crt0.s sets meivt and pre-fills the 256-entry table
// (in DCCM) with a dummy handler; pic_register_handler() overrides one entry.
// Handlers must be declared __attribute__((interrupt("machine"))).

#ifndef SEP_PIC_H
#define SEP_PIC_H

#include <stdint.h>

#include "sep.h"

#define SEP_PIC_MEIP_0 SEP_TOP_PIC_MEIP_BASE_ADDR(0)

// The vector table base symbol from the linker script (1024-byte aligned, 256
// 32-bit entries in DCCM).
extern char INTVEC_BASE[];

typedef void (*pic_handler_t)(void);

static inline void _pic_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

// Install a handler for an interrupt source (vector-table entry source_id).
// Must be a 32-bit store: INTVEC_BASE is a char[] symbol, so a C pointer
// write becomes four `sb`s under -mstrict-align, and EL2 DCCM drops them.
static inline void pic_register_handler(uint32_t source_id, pic_handler_t handler) {
    uint32_t addr = (uint32_t)(uintptr_t)&INTVEC_BASE[source_id * 4u];
    uint32_t val = (uint32_t)(uintptr_t)handler;
    __asm__ volatile("sw %0, 0(%1)" ::"r"(val), "r"(addr) : "memory");
    __asm__ volatile("fence" ::: "memory");
}

// PeakRDL ``SEP_TOP_PIC_*_BASE_ADDR(idx)`` expands ``idx * stride`` without
// parenthesizing idx, so only an atomic argument is safe to pass.
static inline uint32_t _pic_meipl_addr(uint32_t source_id) {
    return SEP_TOP_PIC_MEIPL_BASE_ADDR(source_id);
}

static inline uint32_t _pic_meie_addr(uint32_t source_id) {
    return SEP_TOP_PIC_MEIE_BASE_ADDR(source_id);
}

static inline uint32_t _pic_meigwctrl_addr(uint32_t source_id) {
    return SEP_TOP_PIC_MEIGWCTRL_BASE_ADDR(source_id);
}

static inline uint32_t _pic_meigwclr_addr(uint32_t source_id) {
    return SEP_TOP_PIC_MEIGWCLR_BASE_ADDR(source_id);
}

// Priority 0 disables; 1..15 enable at that level.
static inline void pic_set_priority(uint32_t source_id, uint32_t priority) {
    _pic_wr(_pic_meipl_addr(source_id), priority & EL2_PIC__MEIPL__INTPRIORITY_bm);
}

// type: 0=level, 1=edge. polarity: 0=active-high, 1=active-low.
static inline void pic_set_gateway(uint32_t source_id, uint32_t type, uint32_t polarity) {
    uint32_t val = (polarity & EL2_PIC__MEIGWCTRL__POLARITY_bm) |
                   ((type << EL2_PIC__MEIGWCTRL__IRQ_TYPE_bp) & EL2_PIC__MEIGWCTRL__IRQ_TYPE_bm);
    _pic_wr(_pic_meigwctrl_addr(source_id), val);
}

static inline void pic_enable_source(uint32_t source_id) {
    _pic_wr(_pic_meie_addr(source_id), EL2_PIC__MEIE__INTEN_bm);
}

static inline void pic_disable_source(uint32_t source_id) {
    _pic_wr(_pic_meie_addr(source_id), 0);
}

static inline uint32_t pic_read_source_enable(uint32_t source_id) {
    return *(volatile uint32_t *)_pic_meie_addr(source_id);
}

static inline uint32_t pic_read_priority(uint32_t source_id) {
    return *(volatile uint32_t *)_pic_meipl_addr(source_id);
}

static inline uint32_t pic_read_gateway(uint32_t source_id) {
    return *(volatile uint32_t *)_pic_meigwctrl_addr(source_id);
}

static inline void pic_clear_gateway(uint32_t source_id) {
    _pic_wr(_pic_meigwclr_addr(source_id), 1);
}

static inline uint32_t pic_source_pending(uint32_t source_id) {
    /* meip bitmap is indexed by raw source_id (bit0 unused); neighbours use source_id-1. */
    uint32_t word = *(volatile uint32_t *)SEP_TOP_PIC_MEIP_BASE_ADDR(source_id / 32u);
    return (word >> (source_id % 32u)) & 1u;
}

// Drop the PIC priority threshold/current level to 0 and enable machine
// external interrupts (mie.meie) + global interrupts (mstatus.mie).
#define CSR_MEIPT 0xBC9u    /* VeeR EL2 priority threshold */
#define CSR_MEICURPL 0xBCCu /* VeeR EL2 current priority level */
#define MIE_MEIE (1u << 11)
#define MSTATUS_MIE (1u << 3)

static inline void pic_enable_interrupts(void) {
    __asm__ volatile("csrwi 0xBC9, 0"); /* CSR_MEIPT */
    __asm__ volatile("csrwi 0xBCC, 0"); /* CSR_MEICURPL */
    __asm__ volatile("csrs mie, %0" ::"r"(MIE_MEIE));
    __asm__ volatile("csrs mstatus, %0" ::"r"(MSTATUS_MIE));
}

static inline void pic_disable_interrupts(void) {
    __asm__ volatile("csrc mstatus, %0" ::"r"(MSTATUS_MIE));
}

#endif // SEP_PIC_H
