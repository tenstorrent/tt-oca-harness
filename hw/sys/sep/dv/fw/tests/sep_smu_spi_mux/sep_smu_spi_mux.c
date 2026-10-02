/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_spi_mux — excluded from the firmware build (`FW_TEST_EXCLUDE_NAMES`).
 * The SPI pad select this test name refers to is outside the OCAH hierarchy,
 * so this image only parks in the pass loop. No SPI select exists in OCAH: the
 * OT SPI host reaches the pads only on the SMC LSIO primary plane.
 */

#include "sep_outbound_filter.h"

__attribute__((used, noinline, noreturn)) void smu_sep_spi_mux_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_spi_mux_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

int main(void) {
    sep_outbound_filter_init();
    smu_sep_spi_mux_pass_loop();
}
