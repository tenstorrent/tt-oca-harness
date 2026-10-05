/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * Stackless SMC test-firmware scaffolding -- common helper.
 *
 * For SMU/SMC test flows that bring the SMC up WITHOUT initialising the SRAM
 * stack (e.g. the SMU cocotb backdoor / SEP-driven boot, where the image is
 * preloaded and the cores are re-vectored straight to it). Any SRAM stack
 * access from such firmware wedges the core, so the firmware must be stackless:
 * a naked single-hart entry, absolute-address MMIO, an asm-only busy-wait, and
 * a bounded scratch poll. main() must make NO function calls and use only these
 * macros so the compiler emits no stack frame (verify: no `add sp,sp,-N` in the
 * .dis).
 *
 * Usage:
 *   #include "smc_stackless_test.h"
 *   SMC_STACKLESS_ENTRY(my_test_entry)   // naked entry -> calls main() on hart0
 *   int main(void) { ... use SMC_WR32/RD32/... only, no calls ... }
 * and point +SMC_RESET_SYMBOL / the reset vector at `my_test_entry`.
 ******************************************************************************/
#ifndef SMC_STACKLESS_TEST_H
#define SMC_STACKLESS_TEST_H

#include <stdint.h>

/* Naked single-hart entry: hart0 sets gp/sp and calls main(); harts 1..N park in
 * wfi. Placed in .init and marked used so the linker keeps it as the reset
 * target. */
#define SMC_STACKLESS_ENTRY(name) \
    void name(void) __attribute__((naked, section(".init"), used)); \
    void name(void) { \
        __asm__ volatile(".option push\n" \
                         ".option norvc\n" \
                         "csrr a0, mhartid\n" \
                         "bnez a0, 0f\n" \
                         "la gp, __global_pointer$\n" \
                         "la sp, _sp\n" \
                         "andi sp, sp, -16\n" \
                         "call main\n" \
                         "0:\n" \
                         "wfi\n" \
                         "j 0b\n" \
                         ".option pop\n"); \
    }

/* Absolute-address MMIO (no cached address locals -> no long-lived registers). */
#define SMC_WR32(a, v) (*(volatile uint32_t *)(uintptr_t)(a) = (uint32_t)(v))
#define SMC_RD32(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define SMC_WR64(a, v) (*(volatile uint64_t *)(uintptr_t)(a) = (uint64_t)(v))
#define SMC_RD64(a) (*(volatile uint64_t *)(uintptr_t)(a))
#define SMC_FENCE() __asm__ volatile("fence iorw, iorw" ::: "memory")

/* Deterministic, stackless busy-wait (pure asm, one temporary). n must be a
 * compile-time constant. */
#define SMC_DELAY_ITERS(n) \
    __asm__ volatile("li t0, %0\n1:\n addi t0, t0, -1\n bnez t0, 1b\n" : : "i"(n) : "t0")

/* Bounded poll of an absolute 32-bit address for an exact value; sets okvar
 * (1 = matched, 0 = timed out) without hanging. */
#define SMC_WAIT_EQ(addr, val, limit, okvar) \
    do { \
        okvar = 0; \
        for (uint32_t _i = 0; _i < (uint32_t)(limit); ++_i) { \
            if (SMC_RD32(addr) == (uint32_t)(val)) { \
                okvar = 1; \
                break; \
            } \
        } \
    } while (0)

#endif /* SMC_STACKLESS_TEST_H */
