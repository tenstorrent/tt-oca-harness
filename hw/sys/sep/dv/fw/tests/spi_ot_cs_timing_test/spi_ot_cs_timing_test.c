/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT CS Timing Test
 *
 * Verifies CS timing parameter configuration and write-readback correctness
 * for the CFG register fields: CSNIDLE, CSNLEAD, CSNTRAIL.
 *
 * CFG register fields (all 4-bit, range 0–15):
 * CFG.CSNIDLE  [27:24]: CS idle time between back-to-back transfers
 * CFG.CSNLEAD  [23:20]: CS setup time before first SCLK edge
 * CFG.CSNTRAIL [19:16]: CS hold time after last SCLK edge
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Write min values (all 0): readback verify
 * 3. Write max values (all 15): readback verify
 * 4. Write mixed values (CSNIDLE=5, CSNLEAD=10, CSNTRAIL=3): readback verify
 * 5. Restore to working values (CSNIDLE=2, CSNLEAD=2, CSNTRAIL=2)
 * 6. Issue a simple TX command to verify SPI still operates correctly
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "spi_clk.h"

#define TIMEOUT_LIMIT 100000

static int check_timing(const char *label, uint32_t csnidle, uint32_t csnlead, uint32_t csntrail,
                        uint32_t exp_csnidle, uint32_t exp_csnlead, uint32_t exp_csntrail) {
    int ok = 1;
    printf("  %s:\n", label);
    if (csnidle != exp_csnidle) {
        printf("    CSNIDLE: %u (expected %u) - FAIL\n", csnidle, exp_csnidle);
        ok = 0;
    } else {
        printf("    CSNIDLE: %u - PASS\n", csnidle);
    }
    if (csnlead != exp_csnlead) {
        printf("    CSNLEAD: %u (expected %u) - FAIL\n", csnlead, exp_csnlead);
        ok = 0;
    } else {
        printf("    CSNLEAD: %u - PASS\n", csnlead);
    }
    if (csntrail != exp_csntrail) {
        printf("    CSNTRAIL: %u (expected %u) - FAIL\n", csntrail, exp_csntrail);
        ok = 0;
    } else {
        printf("    CSNTRAIL: %u - PASS\n", csntrail);
    }
    return ok;
}

static int wait_for_ready(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
        timeout--;
    }
    printf("  ERROR: Timeout waiting for READY\n");
    return 1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT CS Timing Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__CONFIGOPTS_t cfg;
    spi_controller__COMMAND_t cmd;
    spi_controller__ERROR_STATUS_t err_status;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    /* ------------------------------------------------------------------ */
    /* Step 1: Min values (CSNIDLE=0, CSNLEAD=0, CSNTRAIL=0)              */
    /* ------------------------------------------------------------------ */
    printf("Step 1: Min CS timing values (all 0)\n");
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 0;
    cfg.f.CSNLEAD = 0;
    cfg.f.CSNTRAIL = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_timing("Min values", cfg.f.CSNIDLE, cfg.f.CSNLEAD, cfg.f.CSNTRAIL, 0, 0, 0))
        pass = 0;

    /* ------------------------------------------------------------------ */
    /* Step 2: Max values (CSNIDLE=15, CSNLEAD=15, CSNTRAIL=15)           */
    /* ------------------------------------------------------------------ */
    printf("\nStep 2: Max CS timing values (all 15)\n");
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CSNIDLE = 15;
    cfg.f.CSNLEAD = 15;
    cfg.f.CSNTRAIL = 15;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_timing("Max values", cfg.f.CSNIDLE, cfg.f.CSNLEAD, cfg.f.CSNTRAIL, 15, 15, 15))
        pass = 0;

    /* ------------------------------------------------------------------ */
    /* Step 3: Mixed values (CSNIDLE=5, CSNLEAD=10, CSNTRAIL=3)           */
    /* ------------------------------------------------------------------ */
    printf("\nStep 3: Mixed CS timing values (CSNIDLE=5, CSNLEAD=10, CSNTRAIL=3)\n");
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CSNIDLE = 5;
    cfg.f.CSNLEAD = 10;
    cfg.f.CSNTRAIL = 3;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_timing("Mixed values", cfg.f.CSNIDLE, cfg.f.CSNLEAD, cfg.f.CSNTRAIL, 5, 10, 3))
        pass = 0;

    /* ------------------------------------------------------------------ */
    /* Step 4: Restore working values and issue a TX command               */
    /* ------------------------------------------------------------------ */
    printf("\nStep 4: Restore working values (all=2) and issue TX command\n");
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    cfg.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR);
    if (!check_timing("Restored values", cfg.f.CSNIDLE, cfg.f.CSNLEAD, cfg.f.CSNTRAIL, 2, 2, 2))
        pass = 0;

    /* Issue a simple 1-byte TX command to verify SPI still works */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x9F000000);
    cmd.w = 0;
    cmd.f.LEN = 0; /* 1 byte */
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;     /* Standard */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x (CMDINVAL=%u CSIDINVAL=%u)\n", err_status.w,
           err_status.f.CMDINVAL, err_status.f.CSIDINVAL);
    if (err_status.f.CMDINVAL || err_status.f.CSIDINVAL) {
        printf("  FAIL: CMD error after restoring CS timing\n");
        pass = 0;
    } else {
        printf("  PASS: TX command accepted after CS timing restore\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT CS TIMING TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT CS TIMING TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
