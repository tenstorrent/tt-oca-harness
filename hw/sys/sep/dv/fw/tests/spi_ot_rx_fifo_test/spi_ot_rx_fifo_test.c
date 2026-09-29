/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT RX FIFO Test
 *
 * Verifies RX FIFO fill, status monitoring (RXQD, RXEMPTY, RXFULL, RXWM),
 * underflow error detection, and RX watermark behavior.
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Verify RXEMPTY=1, RXQD=0 initially
 * 3. Issue 16-byte RX command (MISO=0xFF without flash model)
 * 4. Verify RXQD=4, RXEMPTY=0 after transaction
 * 5. Drain RX FIFO, verify RXQD→0, RXEMPTY=1
 * 6. Test UNDERFLOW (read RXDATA when empty → ERROR_STATUS.underflow=1)
 * 7. Test RXWM: issue RX again with RX_WATERMARK=2, check RXWM=1
 *
 * Note: Without a flash model MISO is 0xFF, so RX words will be 0xFFFFFFFF.
 * The test verifies FIFO behavior (RXQD, RXEMPTY, RXWM), not data content.
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "spi_clk.h"

#define SPI_CLKDIV spi_clkdiv()
#define TIMEOUT_LIMIT 200000
#define RX_LEN_BYTES 16 /* 4 words */

static int wait_for_ready(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
    }
    printf("  TIMEOUT waiting for READY\n");
    return -1;
}

static int wait_for_idle(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
    }
    printf("  TIMEOUT waiting for ACTIVE=0\n");
    return -1;
}

/* Issue an RX-only command of rx_bytes bytes (max 256) */
static void issue_rx_cmd(uint32_t rx_bytes) {
    spi_controller__COMMAND_t cmd;
    cmd.w = 0;
    cmd.f.LEN = rx_bytes - 1;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1; /* RX only */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT RX FIFO Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__STATUS_t status;
    spi_controller__ERROR_STATUS_t err_status;
    uint32_t i;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Configure SPI clock */
    spi_controller__CONFIGOPTS_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = SPI_CLKDIV;
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    printf("SPI controller enabled: CLKDIV=%d\n", SPI_CLKDIV);

    /* -------------------------------------------------------------------
     * Step 1: Verify RX FIFO empty initially
     * ------------------------------------------------------------------- */
    printf("\nStep 1: RX FIFO initial state\n");
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXEMPTY=%u, RXFULL=%u, RXQD=%u\n", status.f.RXEMPTY, status.f.RXFULL, status.f.RXQD);
    if (status.f.RXEMPTY != 1) {
        printf("  FAIL: RXEMPTY should be 1\n");
        pass = 0;
    } else {
        printf("  PASS: RX FIFO empty\n");
    }
    if (status.f.RXQD != 0) {
        printf("  FAIL: RXQD should be 0\n");
        pass = 0;
    } else {
        printf("  PASS: RXQD=0\n");
    }

    /* -------------------------------------------------------------------
     * Step 2: Issue 16-byte RX command and wait for completion
     * Without a flash model MISO=0xFF → 0xFFFFFFFF per word
     * ------------------------------------------------------------------- */
    printf("\nStep 2: Issue RX %u bytes, wait for idle\n", RX_LEN_BYTES);
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    issue_rx_cmd(RX_LEN_BYTES);
    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: transaction did not complete (ACTIVE stuck / no SPI device)\n");
        pass = 0;
        goto done;
    }

    /* -------------------------------------------------------------------
     * Step 3: Verify RXQD and RXEMPTY after transaction
     * ------------------------------------------------------------------- */
    printf("\nStep 3: RX FIFO state after transaction\n");
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXEMPTY=%u, RXQD=%u (expected RXQD=%u)\n", status.f.RXEMPTY, status.f.RXQD,
           RX_LEN_BYTES / 4);
    if (status.f.RXEMPTY != 0) {
        printf("  FAIL: RXEMPTY should be 0 after RX transaction\n");
        pass = 0;
    } else {
        printf("  PASS: RXEMPTY=0 after RX\n");
    }
    if (status.f.RXQD != (RX_LEN_BYTES / 4)) {
        printf("  FAIL: RXQD=%u, expected %u\n", status.f.RXQD, RX_LEN_BYTES / 4);
        pass = 0;
    } else {
        printf("  PASS: RXQD=%u correct\n", status.f.RXQD);
    }

    /* -------------------------------------------------------------------
     * Step 4: Drain RX FIFO, verify RXQD→0 and RXEMPTY→1
     * ------------------------------------------------------------------- */
    printf("\nStep 4: Drain RX FIFO (%u words)\n", RX_LEN_BYTES / 4);
    uint32_t words_read = 0;
    for (i = 0; i < RX_LEN_BYTES / 4; i++) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.RXEMPTY) {
            uint32_t word = READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
            printf("  [%u] 0x%08x\n", i, word);
            words_read++;
        } else {
            printf("  [%u] RX FIFO empty (underrun)\n", i);
        }
    }
    printf("  Read %u/%u words\n", words_read, RX_LEN_BYTES / 4);
    if (words_read != RX_LEN_BYTES / 4) {
        printf("  FAIL: Expected %u words, got %u\n", RX_LEN_BYTES / 4, words_read);
        pass = 0;
    }

    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  After drain: RXEMPTY=%u, RXQD=%u\n", status.f.RXEMPTY, status.f.RXQD);
    if (status.f.RXEMPTY != 1) {
        printf("  FAIL: RXEMPTY should be 1 after draining all words\n");
        pass = 0;
    } else {
        printf("  PASS: RXEMPTY=1 after drain\n");
    }
    if (status.f.RXQD != 0) {
        printf("  FAIL: RXQD should be 0 after drain\n");
        pass = 0;
    } else {
        printf("  PASS: RXQD=0 after drain\n");
    }

    /* -------------------------------------------------------------------
     * Step 5: UNDERFLOW test (read from empty RX FIFO)
     * ------------------------------------------------------------------- */
    printf("\nStep 5: UNDERFLOW test (read empty RX FIFO)\n");
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    uint32_t dummy = READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    (void)dummy;
    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x, UNDERFLOW=%u\n", err_status.w, err_status.f.UNDERFLOW);
    if (err_status.f.UNDERFLOW) {
        printf("  PASS: UNDERFLOW error detected\n");
    } else {
        printf("  FAIL: UNDERFLOW not detected after reading empty RX FIFO\n");
        pass = 0;
    }
    /* Clear UNDERFLOW */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, err_status.w);
    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  After W1C clear: ERROR_STATUS=0x%08x\n", err_status.w);
    if (err_status.f.UNDERFLOW) {
        printf("  FAIL: UNDERFLOW did not clear on W1C write\n");
        pass = 0;
    } else {
        printf("  PASS: UNDERFLOW cleared correctly\n");
    }

    /* -------------------------------------------------------------------
     * Step 6: RXWM test (RX watermark)
     * Set RX_WATERMARK=2, issue 16-byte RX (4 words → RXQD=4 >= WM=2)
     * RXWM should be 1
     * ------------------------------------------------------------------- */
    printf("\nStep 6: RXWM test (RX_WATERMARK=2)\n");
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.RX_WATERMARK = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    issue_rx_cmd(RX_LEN_BYTES);
    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: transaction did not complete (ACTIVE stuck)\n");
        pass = 0;
        goto done;
    }

    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXQD=%u, RX_WM=2, RXWM=%u\n", status.f.RXQD, status.f.RXWM);
    if (status.f.RXWM != 1) {
        printf("  FAIL: RXWM should be 1 (RXQD=%u >= WM=2)\n", status.f.RXQD);
        pass = 0;
    } else {
        printf("  PASS: RXWM=1 correct\n");
    }

    /* Drain and verify RXWM=0 when RXQD drops below WM */
    printf("  Draining 3 words (RXQD expected to become 1, below WM=2)\n");
    for (i = 0; i < 3; i++) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.RXEMPTY) {
            (void)READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
        }
    }
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXQD=%u, RXWM=%u (expected RXWM=0)\n", status.f.RXQD, status.f.RXWM);
    if (status.f.RXWM != 0) {
        printf("  FAIL: RXWM should be 0 when RXQD < WM=2\n");
        pass = 0;
    } else {
        printf("  PASS: RXWM=0 after draining below watermark\n");
    }

    /* Drain remaining */
    for (i = 0; i < 4; i++) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.RXEMPTY) {
            (void)READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
        }
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT RX FIFO TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT RX FIFO TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
