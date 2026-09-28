/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT TX FIFO Test
 *
 * Verifies TX FIFO write, status monitoring (TXQD, TXEMPTY, TXFULL, TXWM),
 * overflow error detection, and SW_RST drain behavior.
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Verify TXEMPTY=1 initially
 * 3. Write multiple words to TXDATA, monitor TXQD
 * 4. Test TX watermark (TXWM) with configurable TX_WATERMARK
 * 5. Write until TXFULL, verify overflow error
 * 6. SW_RST, verify TXEMPTY after reset
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000
#define TX_FILL_LIMIT 256 /* upper bound while probing TXFULL */

static int wait_for_tx_empty(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.TXEMPTY) return 0;
    }
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  FAIL: TIMEOUT waiting for TXEMPTY after SW_RST (STATUS=0x%08x)\n", status.w);
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT TX FIFO Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__STATUS_t status;
    spi_controller__ERROR_STATUS_t err_status;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    ctrl.f.TX_WATERMARK = 4;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Step 1: Verify TX FIFO empty initially */
    printf("\nStep 1: TX FIFO initial state\n");
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TXEMPTY=%u, TXFULL=%u, TXQD=%u\n", status.f.TXEMPTY, status.f.TXFULL, status.f.TXQD);
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
        WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xA0000000 | i);
    }
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  After 8 writes: TXQD=%u, TXEMPTY=%u, TXFULL=%u\n", status.f.TXQD, status.f.TXEMPTY,
           status.f.TXFULL);
    if (status.f.TXEMPTY != 0) {
        printf("  FAIL: TXEMPTY should be 0 after writes\n");
        pass = 0;
    } else {
        printf("  PASS: TXEMPTY cleared after writes\n");
    }
    if (status.f.TXQD != 8) {
        printf("  FAIL: TXQD expected 8 after 8 writes, got %u\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXQD=8 matches issued write count\n");
    }

    /* Step 3: Check TX watermark */
    printf("\nStep 3: TX watermark check (TX_WATERMARK=4)\n");
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TXWM=%u (TXQD=%u, watermark=4)\n", status.f.TXWM, status.f.TXQD);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM should be 0 (TXQD=%u >= WM=4)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 correct (TXQD >= WM=4)\n");
    }

    /* Step 4: Fill TX FIFO until TXFULL (probe capacity; no RTL-transcribed depth) */
    printf("\nStep 4: Fill TX FIFO until TXFULL\n");
    uint32_t fill_count = 8; /* already written in step 2 */
    while (!status.f.TXFULL && fill_count < TX_FILL_LIMIT) {
        WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xB0000000 | fill_count);
        fill_count++;
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    }
    printf("  After %u writes: TXQD=%u, TXFULL=%u\n", fill_count, status.f.TXQD, status.f.TXFULL);
    if (!status.f.TXFULL) {
        printf("  FAIL: TXFULL never asserted after %u writes\n", fill_count);
        pass = 0;
    } else {
        printf("  PASS: TXFULL=1 after %u writes\n", fill_count);
    }
    if (status.f.TXFULL && status.f.TXQD != fill_count) {
        printf("  FAIL: TXQD=%u does not match issued occupancy %u at TXFULL\n", status.f.TXQD,
               fill_count);
        pass = 0;
    } else if (status.f.TXFULL) {
        printf("  PASS: TXQD=%u matches issued occupancy at TXFULL\n", status.f.TXQD);
    }

    /* Step 5: Attempt overflow - write one more word */
    printf("\nStep 5: Overflow test (write when full)\n");
    /* Clear any prior errors */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xDEADBEEF);
    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x, OVERFLOW=%u\n", err_status.w, err_status.f.OVERFLOW);
    if (err_status.f.OVERFLOW) {
        printf("  PASS: Overflow error detected\n");
    } else {
        printf("  FAIL: Overflow not detected after write when TXFULL=1\n");
        pass = 0;
    }

    /* Clear overflow error */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);

    /* Step 6: Software reset and verify drain */
    printf("\nStep 6: SW_RST drain test\n");
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Confirm the drain while SW_RST is still held, then release: the field is a
     * level and the core stays in reset until it is cleared. */
    int drained = wait_for_tx_empty(TIMEOUT_LIMIT);
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    ctrl.f.SW_RST = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    if (drained) {
        pass = 0;
        goto done;
    }

    printf("  After SW_RST: TXEMPTY=%u, TXQD=%u\n", status.f.TXEMPTY, status.f.TXQD);
    if (status.f.TXEMPTY != 1) {
        printf("  FAIL: TXEMPTY should be 1 after SW_RST drain\n");
        pass = 0;
    }
    if (status.f.TXQD != 0) {
        printf("  FAIL: TXQD should be 0 after SW_RST drain (got %u)\n", status.f.TXQD);
        pass = 0;
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT TX FIFO TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT TX FIFO TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
