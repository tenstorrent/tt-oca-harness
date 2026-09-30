/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_spi_mux — excluded from the OSS firmware compile
 * (`FW_TEST_EXCLUDE_NAMES`). The image of this name programs SPI_MUX_CTRL,
 * a register in a companion wrapper outside the OCAH hierarchy, so that image
 * lives with the wrapper. No SPI select exists: the OT SPI host reaches the
 * pads only on the SMC LSIO primary plane.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
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

static void (*const keep_fail)(void) = smu_sep_spi_mux_fail_loop;

int main(void) {
    (void)keep_fail;
    sep_outbound_filter_init();
    smu_sep_spi_mux_pass_loop();
}
