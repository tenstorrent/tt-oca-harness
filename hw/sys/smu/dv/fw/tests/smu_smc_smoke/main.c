// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Minimal no-SEP SMC firmware: publish TEST_PASS through scratch register 0.

#include <stdint.h>

#define SMC_SCRATCH0_ADDR ((uintptr_t)0xC0039080u)
#define SMC_TEST_PASS 0xACAFACA1u

int main(void) {
    *((volatile uint32_t *)SMC_SCRATCH0_ADDR) = SMC_TEST_PASS;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    for (;;) {
        __asm__ volatile("wfi");
    }
}
