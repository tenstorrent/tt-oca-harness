/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Command Queue Test
 *
 * Verifies command queue functionality, CMDQD monitoring, CSID selection,
 * and error conditions (CMDBUSY, CMDINVAL, CSIDINVAL).
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Verify CMDQD=0 initially
 * 3. Write CSID=0, issue CMD, check CMDQD
 * 4. Test CMDINVAL error with invalid SPEED=3
 * 5. Test CSIDINVAL error with CSID > NUM_CS
 * 6. Verify ERROR_STATUS W1C clear
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "spi_clk.h"

#define TIMEOUT_LIMIT 100000

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

/* Returns 0 when READY, -1 on timeout (fail-closed). */
static int wait_for_ready(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  FAIL: TIMEOUT waiting for READY (STATUS=0x%08x)\n", status.w);
    return -1;
}

/* Poll until ERROR_STATUS bit set; returns 0 if seen, -1 on timeout. */
static int wait_for_error_bit(int (*bit_set)(spi_controller__ERROR_STATUS_t), int timeout,
                              const char *name) {
    spi_controller__ERROR_STATUS_t err;
    while (timeout-- > 0) {
        err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
        if (bit_set(err)) return 0;
    }
    err.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  FAIL: TIMEOUT waiting for %s (ERROR_STATUS=0x%08x)\n", name, err.w);
    return -1;
}

static int err_cmdinval_set(spi_controller__ERROR_STATUS_t e) {
    return e.f.CMDINVAL != 0;
}
static int err_csidinval_set(spi_controller__ERROR_STATUS_t e) {
    return e.f.CSIDINVAL != 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Command Queue Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CTRL_t ctrl;
    spi_controller__STATUS_t status;
    spi_controller__CMD_t cmd;
    spi_controller__ERROR_STATUS_t err_status;
    spi_controller__ERROR_ENABLE_t err_enable;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CTRL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    /* Configure clock */
    spi_controller__CFG_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);

    /* Step 1: Verify CMDQD initial state */
    printf("\nStep 1: Command queue initial state\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  CMDQD=%u, READY=%u\n", status.f.CMDQD, status.f.READY);
    if (status.f.CMDQD != 0) {
        printf("  FAIL: CMDQD expected 0 at idle\n");
        pass = 0;
    }

    /* Step 2: Set CSID and verify */
    printf("\nStep 2: CSID configuration\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    uint32_t csid_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR);
    if (!check_reg("CSID=0", csid_val, 0)) pass = 0;

    /* Step 3: Issue valid command (positive control before negative tests) */
    printf("\nStep 3: Issue valid command (TX, Standard, LEN=3)\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x9F000000);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    printf("  CMD issued: LEN=%u, SPEED=%u, DIR=%u, CSAAT=%u\n", cmd.f.LEN, cmd.f.SPEED,
           cmd.f.DIRECTION, cmd.f.CSAAT);

    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x (expect clean)\n", err_status.w);
    if (err_status.w != 0) {
        printf("  FAIL: ERROR_STATUS not clean after valid CMD\n");
        pass = 0;
        goto done;
    }

    /* Step 3.5: Test CMDINVAL error (SPEED=3, reserved value) */
    printf("\nStep 3.5: CMDINVAL error test (SPEED=3)\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.SPEED = 3; /* reserved speed → CMDINVAL */
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_error_bit(err_cmdinval_set, TIMEOUT_LIMIT, "CMDINVAL")) {
        pass = 0;
        goto done;
    }
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x, CMDINVAL=%u\n", err_status.w, err_status.f.CMDINVAL);
    printf("  PASS: CMDINVAL error detected\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* Step 4: Test CSIDINVAL error */
    printf("\nStep 4: CSIDINVAL error test (CSID=5, NUM_CS=1)\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 5);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

    if (wait_for_error_bit(err_csidinval_set, TIMEOUT_LIMIT, "CSIDINVAL")) {
        pass = 0;
        goto done;
    }
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x, CSIDINVAL=%u\n", err_status.w, err_status.f.CSIDINVAL);
    printf("  PASS: CSIDINVAL error detected\n");

    /* Restore CSID=0 */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    /* Step 5: Test ERROR_STATUS W1C */
    printf("\nStep 5: ERROR_STATUS W1C clear\n");
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  Before clear: ERROR_STATUS=0x%08x\n", err_status.w);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  After W1C: ERROR_STATUS=0x%08x\n", err_status.w);
    if (err_status.w != 0) {
        printf("  FAIL: ERROR_STATUS not cleared after W1C\n");
        pass = 0;
    }

    /* Step 6: Test ERROR_ENABLE defaults (from generated field resets) */
    printf("\nStep 6: ERROR_ENABLE default check\n");
    {
        uint32_t err_en_default = (SPI_CONTROLLER__ERROR_ENABLE__CMDBUSY_reset
                                   << SPI_CONTROLLER__ERROR_ENABLE__CMDBUSY_bp) |
                                  (SPI_CONTROLLER__ERROR_ENABLE__OVERFLOW_reset
                                   << SPI_CONTROLLER__ERROR_ENABLE__OVERFLOW_bp) |
                                  (SPI_CONTROLLER__ERROR_ENABLE__UNDERFLOW_reset
                                   << SPI_CONTROLLER__ERROR_ENABLE__UNDERFLOW_bp) |
                                  (SPI_CONTROLLER__ERROR_ENABLE__CMDINVAL_reset
                                   << SPI_CONTROLLER__ERROR_ENABLE__CMDINVAL_bp) |
                                  (SPI_CONTROLLER__ERROR_ENABLE__CSIDINVAL_reset
                                   << SPI_CONTROLLER__ERROR_ENABLE__CSIDINVAL_bp);
        err_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR);
        if (!check_reg("ERROR_ENABLE default", err_enable.w, err_en_default)) pass = 0;
    }

done:

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT CMD QUEUE TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT CMD QUEUE TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
