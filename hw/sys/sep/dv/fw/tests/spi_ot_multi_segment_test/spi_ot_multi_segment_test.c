/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Multi-Segment Test
 *
 * Verifies that multiple SPI command segments can be chained using CSAAT=1
 * to keep CS# asserted across segments (typical flash/QSPI protocol sequence).
 *
 * Segment chain (mimics a quad fast-read sequence):
 * Seg 1 (TX 1B, CSAAT=1): Command byte   (0xEB)
 * Seg 2 (TX 3B, CSAAT=1): 24-bit Address (0x00_1234)
 * Seg 3 (Dum 2cy,CSAAT=1): Mode/dummy cycles
 * Seg 4 (RX 4B, CSAAT=0): Data read, release CS#
 *
 * Checks:
 * - No CMDINVAL or CSIDINVAL error throughout the chain
 * - Controller returns READY between segments (CMDQD drains)
 * - Final CSAAT=0 command completes cleanly
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
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.READY) return 0;
        timeout--;
    }
    printf("  ERROR: Timeout waiting for READY\n");
    return 1;
}

static int wait_for_idle(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (!status.f.ACTIVE) return 0;
        timeout--;
    }
    printf("  WARN: Timeout waiting for ACTIVE=0\n");
    return 1;
}

static int check_no_errors(const char *seg_name) {
    spi_controller__ERROR_STATUS_t err_status;
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err_status.f.CMDINVAL || err_status.f.CSIDINVAL || err_status.f.CMDBUSY) {
        printf("  FAIL %s: ERROR_STATUS=0x%08x (CMDINVAL=%u CSIDINVAL=%u CMDBUSY=%u)\n", seg_name,
               err_status.w, err_status.f.CMDINVAL, err_status.f.CSIDINVAL, err_status.f.CMDBUSY);
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
        return 0;
    }
    printf("  PASS %s: no CMD errors\n", seg_name);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);
    return 1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Multi-Segment Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__CONFIGOPTS_t cfg;
    spi_controller__COMMAND_t cmd;
    spi_controller__STATUS_t status;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Configure: freq-robust 25 MHz SCLK (spi_clkdiv), Mode 0, standard CS timing */
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* ------------------------------------------------------------------ */
    /* Segment 1: TX 1 byte command (0xEB = Quad Fast Read), CSAAT=1      */
    /* ------------------------------------------------------------------ */
    printf("Segment 1: TX cmd byte (0xEB), Standard, CSAAT=1\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  Pre-seg1: CMDQD=%u READY=%u\n", status.f.CMDQD, status.f.READY);

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xEB000000);
    cmd.w = 0;
    cmd.f.LEN = 0;       /* 1 byte */
    cmd.f.CSAAT = 1;     /* keep CS# low */
    cmd.f.SPEED = 0;     /* Standard for command byte */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    if (!check_no_errors("Seg1")) pass = 0;

    /* ------------------------------------------------------------------ */
    /* Segment 2: TX 3 bytes address (0x001234), Quad, CSAAT=1            */
    /* ------------------------------------------------------------------ */
    printf("\nSegment 2: TX 3-byte address (0x001234), Quad, CSAAT=1\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x00123400);
    cmd.w = 0;
    cmd.f.LEN = 2;       /* 3 bytes */
    cmd.f.CSAAT = 1;     /* keep CS# low */
    cmd.f.SPEED = 2;     /* Quad */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    if (!check_no_errors("Seg2")) pass = 0;

    /* ------------------------------------------------------------------ */
    /* Segment 3: Dummy 2 cycles, Quad, CSAAT=1                           */
    /* ------------------------------------------------------------------ */
    printf("\nSegment 3: Dummy 2 cycles, Quad, CSAAT=1\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = 1;       /* 2 dummy cycles */
    cmd.f.CSAAT = 1;     /* keep CS# low */
    cmd.f.SPEED = 2;     /* Quad */
    cmd.f.DIRECTION = 0; /* Dummy */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }
    if (!check_no_errors("Seg3")) pass = 0;

    /* ------------------------------------------------------------------ */
    /* Segment 4: RX 4 bytes data, Quad, CSAAT=0 (final segment)          */
    /* ------------------------------------------------------------------ */
    printf("\nSegment 4: RX 4 bytes, Quad, CSAAT=0 (final — releases CS#)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  Pre-seg4: CMDQD=%u READY=%u\n", status.f.CMDQD, status.f.READY);

    cmd.w = 0;
    cmd.f.LEN = 3;       /* 4 bytes */
    cmd.f.CSAAT = 0;     /* release CS# after */
    cmd.f.SPEED = 2;     /* Quad */
    cmd.f.DIRECTION = 1; /* RX */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: transaction did not complete (ACTIVE stuck)\n");
        pass = 0;
        goto done;
    }

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  Post-seg4: CMDQD=%u ACTIVE=%u RXQD=%u\n", status.f.CMDQD, status.f.ACTIVE,
           status.f.RXQD);
    if (!check_no_errors("Seg4")) pass = 0;

    /* Verify CMDQD returned to 0 after full chain completes */
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("\nFinal state: CMDQD=%u (expected 0)\n", status.f.CMDQD);
    if (status.f.CMDQD != 0) {
        printf("  FAIL: CMDQD should be 0 after all segments complete\n");
        pass = 0;
    } else {
        printf("  PASS: CMDQD=0 (all segments executed)\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT MULTI-SEGMENT TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT MULTI-SEGMENT TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
