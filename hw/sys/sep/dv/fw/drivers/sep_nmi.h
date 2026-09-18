// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VeeR EL2 NMI (non-maskable interrupt) firmware driver for the SEP OSS tests.
// Header-only. Addresses and the vector reset come from generated sep_addr.h /
// sep_cpu_ctrl.h (via sep.h).
//
// VeeR EL2 NMI mechanism (bare `sep`): nmi_int = intr_wdog_timer_bark drives the
// NMI; nmi_vec[31:1] (the jump address) is driven by the SEP_NMI_VEC CSR. The
// trampoline `_nmi_handler` (crt0.s, 256-byte aligned) saves context, CALLs the
// registered C handler via `_nmi_handler_ptr`, and mret-returns. To use:
//   1. nmi_register_handler(my_handler);   // set the C handler
//   2. nmi_set_vector_reg();               // SEP_NMI_VEC = &_nmi_handler
//   3. enable an NMI source (e.g. the WDT bark, sep_wdt.h)

#ifndef SEP_NMI_H
#define SEP_NMI_H

#include <stdint.h>

#include "sep.h"

#define SEP_NMI_VEC_ADDR OCH_SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_BASE_ADDR
#define SEP_NMI_VEC_LOCK_ADDR OCH_SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_BASE_ADDR
// Reset value only. It is a placeholder, not a valid handler -- nothing guarantees
// the image even covers that address, and an uninitialized ICCM fetch there is an
// uncorrectable ECC error that re-raises NMI. Steps 1-2 above must complete before
// any NMI source is enabled.
#define SEP_NMI_VEC_DEFAULT SEP_CPU_CTRL__SEP_NMI_VEC_reset

typedef void (*sep_nmi_handler_t)(void);

// The trampoline + runtime handler pointer (crt0.s).
extern void _nmi_handler(void);
extern sep_nmi_handler_t _nmi_handler_ptr;

static inline void _sep_nmi_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

static inline uint32_t _sep_nmi_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

// Register the C handler the NMI trampoline calls. The fence ensures the pointer
// is visible before an NMI can fire.
static inline void nmi_register_handler(sep_nmi_handler_t handler) {
    _nmi_handler_ptr = handler;
    __asm__ volatile("fence" ::: "memory");
}

// Address programmed into SEP_NMI_VEC: the 256-byte-aligned trampoline.
static inline uint32_t nmi_get_vector_addr(void) {
    return (uint32_t)&_nmi_handler;
}

// Point the hardware NMI vector at the trampoline (call register_handler first).
static inline void nmi_set_vector_reg(void) {
    _sep_nmi_wr(SEP_NMI_VEC_ADDR, nmi_get_vector_addr());
}

// Lock SEP_NMI_VEC (write-once-set; sticky until reset).
static inline void nmi_lock_vector_reg(void) {
    _sep_nmi_wr(SEP_NMI_VEC_LOCK_ADDR, SEP_CPU_CTRL__SEP_NMI_VEC_LOCK__LOCK_bm);
}

static inline uint32_t nmi_read_vector_reg(void) {
    return _sep_nmi_rd(SEP_NMI_VEC_ADDR);
}

static inline uint32_t nmi_read_lock_reg(void) {
    return _sep_nmi_rd(SEP_NMI_VEC_LOCK_ADDR);
}

#endif // SEP_NMI_H
