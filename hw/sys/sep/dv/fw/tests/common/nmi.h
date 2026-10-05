/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * NMI (Non-Maskable Interrupt) Handler Registration
 *
 * VeeR EL2 NMI mechanism:
 *   - nmi_vec[31:1] input provides the handler address
 *   - nmi_int signal triggers the NMI (must be asserted 2+ cycles)
 *   - CPU jumps to nmi_vec address when NMI fires
 *
 * This module provides runtime registration of NMI handlers.
 * The default handler (_default_nmi_handler in crt0.s) fails the test.
 *
 * Usage:
 *   1. Define your NMI handler function (can be in C or assembly)
 *   2. Call nmi_register_handler() to register it
 *   3. Set the NMI vector with nmi_set_vector_reg() (SEP_NMI_VEC CSR)
 *
 * Example:
 *   void my_nmi_handler(void) {
 *       // Handle NMI (e.g., clear INTR_STATE W1C)
 *       // The handler can return normally - mret resumes interrupted code
 *   }
 *
 *   int main(void) {
 *       nmi_register_handler(my_nmi_handler);
 *       nmi_set_vector_reg();
 *       // ... enable NMI source ...
 *   }
 *
 */

#ifndef NMI_H
#define NMI_H

#include <stdint.h>
#include "tb.h"
#include "och_sep_common.h"

/* NMI handler function type - takes no args, returns nothing */
typedef void (*nmi_handler_t)(void);

/* Pointer to current NMI handler (defined in crt0.s) */
extern nmi_handler_t _nmi_handler_ptr;

/* Address of the NMI trampoline (defined in crt0.s) */
extern void _nmi_handler(void);

/*
 * Register a custom NMI handler at runtime.
 *
 * The handler is called when NMI fires. The crt0.s trampoline saves the
 * caller-saved registers and returns with mret, so the handler may return
 * normally.
 *
 * @param handler Function pointer to the custom NMI handler
 */
static inline void nmi_register_handler(nmi_handler_t handler) {
    _nmi_handler_ptr = handler;
    /* Memory barrier to ensure pointer is visible before NMI can fire */
    __asm__ volatile("fence" ::: "memory");
}

/*
 * Get the address of the NMI trampoline.
 *
 * This is the address that should be programmed into nmi_vec.
 * The trampoline will then jump through _nmi_handler_ptr to the
 * actual handler.
 *
 * @return Address of _nmi_handler trampoline (256-byte aligned)
 */
static inline uint32_t nmi_get_vector_addr(void) {
    return (uint32_t)&_nmi_handler;
}

/*
 * Write the LOAD_NMI_ADDR command to the STDOUT mailbox.
 *
 * No SEP testbench decodes LOAD_NMI_ADDR, so this call does not change
 * nmi_vec. Use nmi_set_vector_reg() to set the NMI vector.
 */
static inline void nmi_set_vector(void) {
    uint32_t nmi_addr = nmi_get_vector_addr();
    /*
     * Mailbox command format for LOAD_NMI_ADDR (0x81):
     *   bits [7:0]  = 0x81 (command)
     *   bits [31:8] = nmi_addr >> 8
     */
    uint32_t mailbox_cmd = ((nmi_addr >> 8) << 8) | LOAD_NMI_ADDR;
    WRITE_REG(STDOUT, mailbox_cmd);
}

/*
 * Set the NMI vector via SEP_NMI_VEC register.
 *
 * This writes the NMI vector address directly to the SEP_NMI_VEC
 * hardware register, which the VeeR CPU uses for the NMI jump address.
 *
 * The NMI vector is set to the _nmi_handler trampoline address.
 * Make sure to call nmi_register_handler() first if you want
 * a custom handler.
 */
static inline void nmi_set_vector_reg(void) {
    uint32_t nmi_addr = nmi_get_vector_addr();
    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_BASE_ADDR, nmi_addr);
}

/*
 * Lock the NMI vector register.
 *
 * Once locked, the SEP_NMI_VEC register cannot be modified.
 * The lock is sticky (write-once-set) - it cannot be cleared
 * until reset.
 */
static inline void nmi_lock_vector_reg(void) {
    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_BASE_ADDR, 0x1);
}

/*
 * Read the current NMI vector from the SEP_NMI_VEC register.
 *
 * @return Current NMI vector address
 */
static inline uint32_t nmi_read_vector_reg(void) {
    return READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_BASE_ADDR);
}

/*
 * Read the NMI vector lock status.
 *
 * @return 1 if locked, 0 if unlocked
 */
static inline uint32_t nmi_read_lock_reg(void) {
    return READ_REG(SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_BASE_ADDR);
}

#endif /* NMI_H */
