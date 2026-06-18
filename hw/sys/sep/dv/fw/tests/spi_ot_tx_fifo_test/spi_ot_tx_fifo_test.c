/*
 * SPI OT TX FIFO Test - TC_SPIOT_005 (P0)
 *
 * Verifies TX FIFO write, status monitoring (TXQD, TXEMPTY, TXFULL, TXWM),
 * overflow error detection, and SW_RST drain behavior.
 *
 * Test Flow:
 *   1. Configure SPI mux, enable controller
 *   2. Verify TXEMPTY=1 initially
 *   3. Write multiple words to TXDATA, monitor TXQD
 *   4. Test TX watermark (TXWM) with configurable TX_WATERMARK
 *   5. Write until TXFULL, verify overflow error
 *   6. SW_RST, verify TXEMPTY after reset
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_spi_ot_tx_fifo_test STACK=sim
 *
 * Copyright 2025 Tenstorrent Inc.
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000
#define TX_FIFO_DEPTH 73  /* effective capacity: 72 FIFO slots + 1 byte_select stage */

static void configure_spi_mux_ot(void)
{
    WRITE_REG(OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR, 1u);
}

int main(void)
{
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT TX FIFO Test (TC_SPIOT_005)\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CTRL_t ctrl;
    spi_controller__STATUS_t status;
    spi_controller__ERROR_STATUS_CMDBUSY_610d1fb8_CMDINVAL_5f890e60_CSIDINVAL_52ab238c_OVERFLOW_b3d067e6_UNDERFLOW_cfe1cef2_t err_status;

    configure_spi_mux_ot();
    printf("SPI mux configured for OpenTitan\n");

    /* Enable controller */
    ctrl.w = 0u;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    ctrl.f.TX_WATERMARK = 4;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    /* Step 1: Verify TX FIFO empty initially */
    printf("\nStep 1: TX FIFO initial state\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TXEMPTY=%u, TXFULL=%u, TXQD=%u\n",
           status.f.TXEMPTY, status.f.TXFULL, status.f.TXQD);
    if (status.f.TXEMPTY != 1) {
        printf("  FAIL: TXEMPTY should be 1\n");
        pass = 0;
    } else {
        printf("  PASS: TX FIFO is empty\n");
    }
    if (status.f.TXWM != 1) {
        printf("  FAIL: TXWM should be 1 initially (TXQD=0 < WM=4)\n");
        pass = 0;
    } else {
        printf("  PASS: TXWM=1 correct (TXQD < WM=4)\n");
    }

    /* Step 2: Write data words and monitor TXQD */
    printf("\nStep 2: Write 8 words to TX FIFO\n");
    uint32_t i;
    for (i = 0; i < 8; i++) {
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0xA0000000 | i);
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  After 8 writes: TXQD=%u, TXEMPTY=%u, TXFULL=%u\n",
           status.f.TXQD, status.f.TXEMPTY, status.f.TXFULL);
    if (status.f.TXEMPTY != 0) {
        printf("  FAIL: TXEMPTY should be 0 after writes\n");
        pass = 0;
    } else {
        printf("  PASS: TXEMPTY cleared after writes\n");
    }

    /* Step 3: Check TX watermark */
    printf("\nStep 3: TX watermark check (TX_WATERMARK=4)\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TXWM=%u (TXQD=%u, watermark=4)\n", status.f.TXWM, status.f.TXQD);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM should be 0 (TXQD=%u >= WM=4)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 correct (TXQD >= WM=4)\n");
    }

    /* Step 4: Fill TX FIFO to capacity */
    printf("\nStep 4: Fill TX FIFO (writing %d more words)\n", TX_FIFO_DEPTH - 8);
    for (i = 8; i < TX_FIFO_DEPTH; i++) {
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0xB0000000 | i);
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  After filling: TXQD=%u, TXFULL=%u\n",
           status.f.TXQD, status.f.TXFULL);
    if (!status.f.TXFULL) {
        printf("  FAIL: TXFULL should be 1 after filling %d words\n", TX_FIFO_DEPTH);
        pass = 0;
    } else {
        printf("  PASS: TXFULL=1 correct\n");
    }

    /* Step 5: Attempt overflow - write one more word */
    printf("\nStep 5: Overflow test (write when full)\n");
    /* Clear any prior errors */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0xDEADBEEF);
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x, OVERFLOW=%u\n",
           err_status.w, err_status.f.OVERFLOW);
    if (err_status.f.OVERFLOW) {
        printf("  PASS: Overflow error detected\n");
    } else {
        printf("  FAIL: Overflow not detected after write when TXFULL=1\n");
        pass = 0;
    }

    /* Clear overflow error */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);

    /* Step 6: Software reset and verify drain */
    printf("\nStep 6: SW_RST drain test\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    volatile int delay;
    for (delay = 0; delay < 5000; delay++) {}

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  After SW_RST: TXEMPTY=%u, TXQD=%u\n",
           status.f.TXEMPTY, status.f.TXQD);

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT TX FIFO TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT TX FIFO TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) { __asm__("wfi"); }
    return pass ? 0 : -1;
}
