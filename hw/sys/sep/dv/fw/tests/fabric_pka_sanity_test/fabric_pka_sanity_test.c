/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Fabric PKA Sanity Test
 *
 * Verifies the SEP fabric path to cpu_ctrl PKA/OTBN-facing control CSRs.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

static int check_eq(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);

    printf("%s: 0x%08x expected 0x%08x - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

int main(void) {
    int pass = 1;

    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("Fabric PKA Sanity Test\n");
    printf("========================================\n\n");

    sep_cpu_ctrl__CLOCK_GATE_CTRL_t cg = {
        .w = READ_REG(SEP_TOP_SEP_CPU_CTRL_CLOCK_GATE_CTRL_BASE_ADDR)};
    printf("CLOCK_GATE_CTRL initial = 0x%08x\n", (uint32_t)cg.w);

    cg.f.pka_cg_enable = 1;
    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_CLOCK_GATE_CTRL_BASE_ADDR, (uint32_t)cg.w);

    sep_cpu_ctrl__CLOCK_GATE_CTRL_t cg_rb = {
        .w = READ_REG(SEP_TOP_SEP_CPU_CTRL_CLOCK_GATE_CTRL_BASE_ADDR)};
    if (cg_rb.f.pka_cg_enable != 1) {
        printf("PKA clock gate did not stay enabled\n");
        pass = 0;
    }

    sep_cpu_ctrl__PKA_CTRL_t pka = {.w = READ_REG(SEP_TOP_SEP_CPU_CTRL_PKA_CTRL_BASE_ADDR)};
    printf("PKA_CTRL initial = 0x%08x dpa_disable=%u noise_src=%u noise_valid=%u\n", pka.w,
           pka.f.pka_dpa_disable, pka.f.pka_noise_src, pka.f.pka_noise_src_valid);

    pka.f.pka_dpa_disable = 1;
    pka.f.pka_noise_src = 1;
    pka.f.pka_noise_src_valid = 1;
    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_PKA_CTRL_BASE_ADDR, pka.w);

    sep_cpu_ctrl__PKA_CTRL_t pka_rb = {.w = READ_REG(SEP_TOP_SEP_CPU_CTRL_PKA_CTRL_BASE_ADDR)};
    if (!check_eq("PKA_CTRL RW", pka_rb.w, pka.w)) {
        pass = 0;
    }

    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_PKA_CTRL_BASE_ADDR, 0u);

    if (pass) {
        printf("=== FABRIC PKA SANITY TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== FABRIC PKA SANITY TEST FAILED ===\n");
        test_fail(0);
    }

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
