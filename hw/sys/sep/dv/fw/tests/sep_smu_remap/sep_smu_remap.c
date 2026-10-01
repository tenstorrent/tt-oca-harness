/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_remap - SMU-level SEP AP/STEE output-remap CSR frontdoor.
 *
 * Programs region-0 offsets via AXI-lite CSR (no TB Force of remap_table),
 * then parks in pass/fail loops for cocotb PC classification.
 *
 * Known offsets (must match cocotb golden check):
 *   AP   region0 = 0x00ABC00000
 *   STEE region0 = 0x0055000000
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

#define AP_REGION0_OFFSET 0x00ABC00000ull
#define STEE_REGION0_OFFSET 0x0055000000ull

static int program_output_remap(void) {
    output_remap__output_remap_region__REGION_ATTRS_t ap;
    output_remap__output_remap_region__REGION_ATTRS_t stee;

    /* Write-only programming; cocotb observes remap_table after pass_loop. */
    ap.w = 0;
    ap.f.offset = AP_REGION0_OFFSET;
    ap.f.valid = 1;
    WRITE_REG64(SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(0), ap.w);

    stee.w = 0;
    stee.f.offset = STEE_REGION0_OFFSET;
    stee.f.valid = 1;
    WRITE_REG64(SEP_TOP_STEE_OUTPUT_REMAP_CTRL_REGION_REGION_ATTRS_BASE_ADDR(0), stee.w);

    return 0;
}

__attribute__((used, noinline, noreturn)) void smu_sep_remap_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

/* Distinct body from pass_loop so ICF cannot fold the symbols together. */
__attribute__((used, noinline, noreturn)) void smu_sep_remap_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
        __asm__ volatile("nop");
    }
}

static void (*const keep_fail)(void) = smu_sep_remap_fail_loop;

int main(void) {
    (void)keep_fail;
    sep_outbound_filter_init();
    if (program_output_remap() == 0) {
        smu_sep_remap_pass_loop();
    } else {
        keep_fail();
    }
}
