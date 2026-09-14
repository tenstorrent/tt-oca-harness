/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * VeeR EL2 PIC interrupt utilities
 *
 * Uses RDL-generated constants from sep.h / sep_addr.h
 */

#include "interrupt.h"
#include "sep.h"

extern char INTVEC_BASE[];

// Helper to write a PIC register with fence
static inline void pic_write_reg(uint32_t addr, uint32_t value) {
    volatile uint32_t *reg = (volatile uint32_t *)addr;
    *reg = value;
    __asm__ volatile("fence" ::: "memory");
}

void pic_register_handler(uint32_t source_id, pic_handler_t handler) {
    // Must be a 32-bit store: INTVEC_BASE is a char[] symbol, so a C pointer
    // write becomes four `sb`s under -mstrict-align, and EL2 DCCM drops them.
    uint32_t addr = (uint32_t)(uintptr_t)&INTVEC_BASE[source_id * 4u];
    uint32_t val = (uint32_t)(uintptr_t)handler;
    __asm__ volatile("sw %0, 0(%1)" ::"r"(val), "r"(addr) : "memory");
    __asm__ volatile("fence" ::: "memory");
}

void pic_set_priority(uint32_t source_id, uint32_t priority) {
    uint32_t addr = OCH_SEP_TOP_PIC_MEIPL_BASE_ADDR(source_id);
    pic_write_reg(addr, priority & EL2_PIC__MEIPL__INTPRIORITY_bm);
}

void pic_set_gateway(uint32_t source_id, uint32_t type, uint32_t polarity) {
    uint32_t addr = OCH_SEP_TOP_PIC_MEIGWCTRL_BASE_ADDR(source_id);
    el2_pic__MEIGWCTRL_t val = {.f = {.polarity = polarity & 0x1, .irq_type = type & 0x1}};
    pic_write_reg(addr, val.w);
}

void pic_enable_source(uint32_t source_id) {
    uint32_t addr = OCH_SEP_TOP_PIC_MEIE_BASE_ADDR(source_id);
    pic_write_reg(addr, 1);
}

void pic_disable_source(uint32_t source_id) {
    uint32_t addr = OCH_SEP_TOP_PIC_MEIE_BASE_ADDR(source_id);
    pic_write_reg(addr, 0);
}

void pic_enable_interrupts(void) {
    __asm__ volatile("csrwi 0xBC9, 0");                 // meipt = 0
    __asm__ volatile("csrwi 0xBCC, 0");                 // meicurpl = 0
    __asm__ volatile("csrs mie, %0" ::"r"(1 << 11));    // mie.meie
    __asm__ volatile("csrs mstatus, %0" ::"r"(1 << 3)); // mstatus.mie
}

void pic_disable_interrupts(void) {
    __asm__ volatile("csrc mstatus, %0" ::"r"(1 << 3)); // mstatus.mie
}
