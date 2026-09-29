/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Standard SPI TX/RX Test
 *
 * Verifies Standard SPI (x1) transmit and receive using the OpenTitan SPI
 * controller FIFO-based command interface.
 *
 * This test exercises the command/data path without requiring an external
 * SPI flash model. It validates the controller accepts commands and data,
 * and monitors STATUS/ERROR registers during the transaction.
 *
 * Test Flow:
 * 1. Enable controller, set clock/config
 * 2. Load TX data into FIFO
 * 3. Issue TX command (Standard SPI, CSAAT=0)
 * 4. Monitor STATUS.ACTIVE until transaction completes
 * 5. Check for errors
 * 6. Issue multi-byte TX+RX sequence
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "spi_clk.h"

#define TIMEOUT_LIMIT 100000

static int wait_for_ready(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
        timeout--;
    }
    printf("  ERROR: Timeout waiting for READY\n");
    return 1;
}

static int wait_for_idle(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout > 0) {
        status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
        timeout--;
    }
    printf("  ERROR: Timeout waiting for ACTIVE=0\n");
    return 1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Standard SPI TX/RX Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__STATUS_t status;
    spi_controller__COMMAND_t cmd;
    spi_controller__CONFIGOPTS_t cfg;
    spi_controller__ERROR_STATUS_t err_status;
    uint32_t i;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Configure: freq-robust 25 MHz SCLK (spi_clkdiv), CPOL=0, CPHA=0, CS timing */
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    /* Set CSID=0 */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);

    /* Clear errors */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* Step 1: Simple TX command */
    printf("Step 1: Single byte TX (Standard SPI)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Load TX data: 1 word with command byte 0x9F (JEDEC READ ID) */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x9F000000);

    /* Issue CMD: TX, Standard speed, 1 byte (LEN=0 means 1 byte) */
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    printf("  CMD issued: DIR=TX, SPEED=Standard, LEN=0 (1 byte)\n");

    /* Wait for completion */
    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: Transaction did not complete (ACTIVE stuck)\n");
        pass = 0;
        goto done;
    }

    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS after TX: 0x%08x\n", err_status.w);
    if (err_status.w != 0) {
        printf("  FAIL: Unexpected ERROR_STATUS after TX (0x%08x)\n", err_status.w);
        pass = 0;
        goto done;
    }

    /* Step 2: Multi-byte TX */
    printf("\nStep 2: Multi-byte TX (4 bytes, CSAAT=1)\n");
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x03001000);

    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 1;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    printf("  CMD issued: DIR=TX, LEN=3 (4 bytes), CSAAT=1\n");

    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS: ACTIVE=%u, TXQD=%u, CMDQD=%u\n", status.f.ACTIVE, status.f.TXQD,
           status.f.CMDQD);

    /* Step 3: Issue RX command (following TX with CSAAT) */
    printf("\nStep 3: RX command (4 bytes, CSAAT=0, release CS)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = 3;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;
    cmd.f.DIRECTION = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);
    printf("  CMD issued: DIR=RX, LEN=3 (4 bytes), CSAAT=0\n");

    /* Wait for completion */
    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: RX transaction did not complete (ACTIVE stuck)\n");
        pass = 0;
        goto done;
    }

    /* Check RX FIFO — require data after successful RX command */
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS: RXQD=%u, RXEMPTY=%u\n", status.f.RXQD, status.f.RXEMPTY);

    /* RXQD counts words; 4-byte RX packs into one RXDATA word */
    if (status.f.RXQD < 1) {
        printf("  FAIL: Expected RXQD>=1 after 4-byte RX (got RXQD=%u)\n", status.f.RXQD);
        pass = 0;
        goto done;
    }
    {
        /* No SPI-peer golden exists for this standard RX path, so only FIFO
         * occupancy is checked (above); the payload is logged, not compared. */
        uint32_t rxdata = READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
        printf("  RXDATA[0]: 0x%08x (4-byte RX packed; no peer golden)\n", rxdata);
        (void)i;
    }

    /* Step 4: Verify no sticky ERROR_STATUS bits after the directed sequence */
    printf("\nStep 4: Final error check\n");
    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x\n", err_status.w);
    printf("  CMDBUSY=%u, OVERFLOW=%u, UNDERFLOW=%u, CMDINVAL=%u, CSIDINVAL=%u\n",
           err_status.f.CMDBUSY, err_status.f.OVERFLOW, err_status.f.UNDERFLOW,
           err_status.f.CMDINVAL, err_status.f.CSIDINVAL);

    if (err_status.f.CMDBUSY || err_status.f.OVERFLOW || err_status.f.UNDERFLOW ||
        err_status.f.CMDINVAL || err_status.f.CSIDINVAL) {
        printf("  FAIL: unexpected ERROR_STATUS bits set\n");
        pass = 0;
    } else {
        printf("  PASS: ERROR_STATUS clear\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT STANDARD SPI TXRX TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT STANDARD SPI TXRX TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
