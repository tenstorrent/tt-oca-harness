/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Clock Config Test
 *
 * Verifies SPI clock divider (CLKDIV), polarity (CPOL), phase (CPHA),
 * full-cycle mode (FULLCYC), and CS timing (CSNIDLE, CSNLEAD, CSNTRAIL).
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Test CLKDIV values: 0, 49, 0xFFFF
 * 3. Test all 4 SPI modes (CPOL/CPHA combinations)
 * 4. Test FULLCYC mode
 * 5. Test CS timing fields (CSNIDLE, CSNLEAD, CSNTRAIL)
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Clock Config Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONFIGOPTS_t cfg;

    /* Step 1: Verify CFG default */
    printf("Step 1: CFG default check\n");
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("CFG default", cfg.w, SPI_CONTROLLER__CONFIGOPTS_reset)) pass = 0;

    /* Step 2: Test CLKDIV values */
    printf("\nStep 2: CLKDIV values\n");

    cfg.w = 0;
    cfg.f.CLKDIV = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("CLKDIV=0 (fastest)", cfg.f.CLKDIV, 0)) pass = 0;

    cfg.w = 0;
    cfg.f.CLKDIV = 49;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("CLKDIV=49 (1MHz@50MHz)", cfg.f.CLKDIV, 49)) pass = 0;

    cfg.w = 0;
    cfg.f.CLKDIV = 0xFFFF;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("CLKDIV=0xFFFF (max)", cfg.f.CLKDIV, 0xFFFF)) pass = 0;

    /* Step 3: Test all 4 SPI modes */
    printf("\nStep 3: SPI modes (CPOL/CPHA)\n");
    uint32_t cpol, cpha;
    for (cpol = 0; cpol <= 1; cpol++) {
        for (cpha = 0; cpha <= 1; cpha++) {
            cfg.w = 0;
            cfg.f.CPOL = cpol;
            cfg.f.CPHA = cpha;
            WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
            cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
            printf("  Mode %u (CPOL=%u, CPHA=%u): readback CPOL=%u, CPHA=%u - %s\n",
                   (cpol << 1) | cpha, cpol, cpha, cfg.f.CPOL, cfg.f.CPHA,
                   (cfg.f.CPOL == cpol && cfg.f.CPHA == cpha) ? "PASS" : "FAIL");
            if (cfg.f.CPOL != cpol || cfg.f.CPHA != cpha) pass = 0;
        }
    }

    /* Step 4: Test FULLCYC */
    printf("\nStep 4: FULLCYC mode\n");
    cfg.w = 0;
    cfg.f.FULLCYC = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("FULLCYC=1", cfg.f.FULLCYC, 1)) pass = 0;

    cfg.f.FULLCYC = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("FULLCYC=0", cfg.f.FULLCYC, 0)) pass = 0;

    /* Step 5: Test CS timing fields */
    printf("\nStep 5: CS timing fields\n");
    cfg.w = 0;
    cfg.f.CSNIDLE = 0xF;
    cfg.f.CSNLEAD = 0xF;
    cfg.f.CSNTRAIL = 0xF;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("CSNIDLE=0xF", cfg.f.CSNIDLE, 0xF)) pass = 0;
    if (!check_reg("CSNLEAD=0xF", cfg.f.CSNLEAD, 0xF)) pass = 0;
    if (!check_reg("CSNTRAIL=0xF", cfg.f.CSNTRAIL, 0xF)) pass = 0;

    cfg.w = 0;
    cfg.f.CSNIDLE = 0;
    cfg.f.CSNLEAD = 0;
    cfg.f.CSNTRAIL = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    {
        const uint32_t cs_timing_bm = SPI_CONTROLLER__CONFIGOPTS__CSNIDLE_bm |
                                      SPI_CONTROLLER__CONFIGOPTS__CSNTRAIL_bm |
                                      SPI_CONTROLLER__CONFIGOPTS__CSNLEAD_bm;
        if (!check_reg("CS timing all zero", cfg.w & cs_timing_bm, 0)) pass = 0;
    }

    /* Step 6: Combined configuration */
    printf("\nStep 6: Combined config (CLKDIV=9, Mode3, FULLCYC, timing)\n");
    cfg.w = 0;
    cfg.f.CLKDIV = 9;
    cfg.f.CPOL = 1;
    cfg.f.CPHA = 1;
    cfg.f.FULLCYC = 1;
    cfg.f.CSNIDLE = 4;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 3;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_reg("CLKDIV", cfg.f.CLKDIV, 9)) pass = 0;
    if (!check_reg("CPOL", cfg.f.CPOL, 1)) pass = 0;
    if (!check_reg("CPHA", cfg.f.CPHA, 1)) pass = 0;
    if (!check_reg("FULLCYC", cfg.f.FULLCYC, 1)) pass = 0;
    if (!check_reg("CSNIDLE", cfg.f.CSNIDLE, 4)) pass = 0;
    if (!check_reg("CSNLEAD", cfg.f.CSNLEAD, 2)) pass = 0;
    if (!check_reg("CSNTRAIL", cfg.f.CSNTRAIL, 3)) pass = 0;

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT CLOCK CONFIG TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT CLOCK CONFIG TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
