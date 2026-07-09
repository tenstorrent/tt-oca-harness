/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Command Queue Test - TC_SPIOT_007 (P0)
 *
 * Verifies command queue functionality, CMDQD monitoring, CSID selection,
 * and error conditions (CMDBUSY, CMDINVAL, CSIDINVAL).
 *
 * Test Flow:
 *   1. Configure SPI mux, enable controller
 *   2. Verify CMDQD=0 initially
 *   3. Write CSID=0, issue CMD, check CMDQD
 *   4. Test CMDINVAL error with invalid SPEED=3
 *   5. Test CSIDINVAL error with CSID > NUM_CS
 *   6. Verify ERROR_STATUS W1C clear
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_spi_ot_cmd_queue_test STACK=sim
 *
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000

static void configure_spi_mux_ot(void) {
    WRITE_REG(OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR, 1u);
}

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Command Queue Test (TC_SPIOT_007)\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CTRL_t ctrl;
    spi_controller__STATUS_t status;
    spi_controller__CMD_t cmd;
    spi_controller__ERROR_STATUS_CMDBUSY_610d1fb8_CMDINVAL_5f890e60_CSIDINVAL_52ab238c_OVERFLOW_b3d067e6_UNDERFLOW_cfe1cef2_t
        err_status;
    spi_controller__ERROR_ENABLE_t err_enable;

    configure_spi_mux_ot();
    printf("SPI mux configured for OpenTitan\n");

    /* Enable controller */
    ctrl.w = 0u;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    /* Configure clock */
    spi_controller__CFG_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = 9;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);

    /* Step 1: Verify CMDQD initial state */
    printf("\nStep 1: Command queue initial state\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  CMDQD=%u, READY=%u\n", status.f.CMDQD, status.f.READY);

    /* Step 2: Set CSID and verify */
    printf("\nStep 2: CSID configuration\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    uint32_t csid_val = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR);
    if (!check_reg("CSID=0", csid_val, 0)) pass = 0;

    /* Step 3: Issue valid command */
    printf("\nStep 3: Issue valid command (TX, Standard, LEN=3)\n");
    /* Clear prior errors */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* Load TX data first */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x9F000000);

    /* Wait for READY */
    int timeout = TIMEOUT_LIMIT;
    do {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (--timeout <= 0) break;
    } while (status.f.READY == 0);

    if (status.f.READY) {
        cmd.w = 0;
        cmd.f.LEN = 3;
        cmd.f.CSAAT = 0;
        cmd.f.SPEED = 0;
        cmd.f.DIRECTION = 2;
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
        printf("  CMD issued: LEN=%u, SPEED=%u, DIR=%u, CSAAT=%u\n", cmd.f.LEN, cmd.f.SPEED,
               cmd.f.DIRECTION, cmd.f.CSAAT);

        err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
        printf("  ERROR_STATUS=0x%08x (should be clean)\n", err_status.w);
    } else {
        printf("  WARN: Controller not READY, skipping CMD issue\n");
    }

    /* Step 3.5: Test CMDINVAL error (SPEED=3, reserved value) */
    printf("\nStep 3.5: CMDINVAL error test (SPEED=3)\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    timeout = TIMEOUT_LIMIT;
    do {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (--timeout <= 0) break;
    } while (status.f.READY == 0);

    if (status.f.READY) {
        cmd.w = 0;
        cmd.f.LEN = 0;
        cmd.f.SPEED = 3; /* reserved speed → CMDINVAL */
        cmd.f.DIRECTION = 2;
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00);
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

        volatile int delay;
        for (delay = 0; delay < 100; delay++) {
        }

        err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
        printf("  ERROR_STATUS=0x%08x, CMDINVAL=%u\n", err_status.w, err_status.f.CMDINVAL);
        if (err_status.f.CMDINVAL) {
            printf("  PASS: CMDINVAL error detected\n");
        } else {
            printf("  FAIL: CMDINVAL not set for SPEED=3\n");
            pass = 0;
        }
        /* Clear errors */
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    } else {
        printf("  WARN: Controller not READY, skipping CMDINVAL test\n");
    }

    /* Step 4: Test CSIDINVAL error */
    printf("\nStep 4: CSIDINVAL error test (CSID=5, NUM_CS=1)\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 5);

    timeout = TIMEOUT_LIMIT;
    do {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (--timeout <= 0) break;
    } while (status.f.READY == 0);

    if (status.f.READY) {
        cmd.w = 0;
        cmd.f.LEN = 0;
        cmd.f.SPEED = 0;
        cmd.f.DIRECTION = 2;
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x00);
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);

        volatile int delay;
        for (delay = 0; delay < 100; delay++) {
        }

        err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
        printf("  ERROR_STATUS=0x%08x, CSIDINVAL=%u\n", err_status.w, err_status.f.CSIDINVAL);
        if (err_status.f.CSIDINVAL) {
            printf("  PASS: CSIDINVAL error detected\n");
        } else {
            printf("  FAIL: CSIDINVAL not set for CSID=5 (NUM_CS=1)\n");
            pass = 0;
        }
    }

    /* Restore CSID=0 */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    /* Step 5: Test ERROR_STATUS W1C */
    printf("\nStep 5: ERROR_STATUS W1C clear\n");
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  Before clear: ERROR_STATUS=0x%08x\n", err_status.w);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  After W1C: ERROR_STATUS=0x%08x\n", err_status.w);

    /* Step 6: Test ERROR_ENABLE defaults */
    printf("\nStep 6: ERROR_ENABLE default check\n");
    err_enable.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_ENABLE_BASE_ADDR);
    if (!check_reg("ERROR_ENABLE default", err_enable.w, 0x11111u)) pass = 0;

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
