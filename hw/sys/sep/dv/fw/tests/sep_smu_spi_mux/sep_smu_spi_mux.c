/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_spi_mux — pad-mux programming belongs with the nonfree wrapper.
 *
 * This directory is excluded from the OSS firmware compile
 * (`FW_TEST_EXCLUDE_NAMES`). The open DUT has no pad mux to program.
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
