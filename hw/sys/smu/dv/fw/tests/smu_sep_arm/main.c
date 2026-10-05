// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SMC firmware for the SEP boot smoke: it reports SMC pass and leaves the SEP
// on its default run gate.
//
// Do not drive the CLA run-request custom actions here: holding them across
// SEP reset release leaves the SEP core in an unknown halt state that never
// fetches its boot ROM.

#include <stdint.h>

#define SMC_SCRATCH0_ADDR ((uintptr_t)0xC0039080u)
#define SMC_TEST_PASS 0xACAFACA1u

int main(void) {
    *((volatile uint32_t *)SMC_SCRATCH0_ADDR) = SMC_TEST_PASS;
    for (;;) {
        __asm__ volatile("wfi");
    }
}
