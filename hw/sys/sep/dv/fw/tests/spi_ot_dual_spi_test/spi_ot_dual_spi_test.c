/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Dual SPI Test
 *
 * Verifies Dual SPI (x2) mode transmit, dummy cycles, and receive using
 * CMD.SPEED=1. Also verifies that DIRECTION=3 (bidirectional) at Dual speed
 * triggers CMDINVAL (bidirectional only valid at Standard speed), and that
 * bidirectional works correctly at SPEED=0 (Standard).
 *
 * A typical dual read sequence: TX cmd/addr → Dummy cycles → RX data.
 * Two data lines (SD[1:0]) are active in Dual mode.
 *
 * Test Flow:
 * 1. Enable controller (freq-robust 25 MHz SCLK (spi_clkdiv), Mode 0)
 * 2. Dual TX: SPEED=1, DIRECTION=2, LEN=3 (4 bytes), CSAAT=1
 * 3. Dual Dummy: SPEED=1, DIRECTION=0, LEN=7 (8 dummy cycles), CSAAT=1
 * 4. Dual RX: SPEED=1, DIRECTION=1, LEN=3 (4 bytes), CSAAT=0
 * 5. CMDINVAL test: SPEED=1 + DIRECTION=3 (bidirectional) must fail
 * 6. Verify bidirectional (DIRECTION=3) accepted at Standard speed (SPEED=0)
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
    printf("  WARN: Timeout waiting for ACTIVE=0 (no SPI device attached)\n");
    return 1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Dual SPI Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__CONFIGOPTS_t cfg;
    spi_controller__COMMAND_t cmd;
    spi_controller__STATUS_t status;
    spi_controller__ERROR_STATUS_t err_status;

    /* Enable controller */
    ctrl.w = SPI_CONTROLLER__CONTROL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Configure: freq-robust 25 MHz SCLK (spi_clkdiv), SPI Mode 0, standard CS timing */
    cfg.w = 0;
    cfg.f.CLKDIV = spi_clkdiv();
    cfg.f.CPOL = 0;
    cfg.f.CPHA = 0;
    cfg.f.CSNIDLE = 2;
    cfg.f.CSNLEAD = 2;
    cfg.f.CSNTRAIL = 2;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* ------------------------------------------------------------------ */
    /* Step 1: Dual TX (SPEED=1, DIRECTION=2)                              */
    /* ------------------------------------------------------------------ */
    printf("Step 1: Dual SPI TX (SPEED=Dual, DIR=TX, LEN=3=4bytes, CSAAT=1)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    /* Load TX FIFO: dual fast-read command pattern */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x3B000000);

    cmd.w = 0;
    cmd.f.LEN = 3;       /* 4 bytes (LEN+1 bytes total) */
    cmd.f.CSAAT = 1;     /* keep CS# low for next segment */
    cmd.f.SPEED = 1;     /* Dual */
    cmd.f.DIRECTION = 2; /* TX */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x (CMDINVAL=%u CSIDINVAL=%u)\n", err_status.w,
           err_status.f.CMDINVAL, err_status.f.CSIDINVAL);
    if (err_status.f.CMDINVAL || err_status.f.CSIDINVAL) {
        printf("  FAIL: CMD error for valid Dual TX command\n");
        pass = 0;
    } else {
        printf("  PASS: Dual TX accepted (no CMDINVAL)\n");
    }
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* ------------------------------------------------------------------ */
    /* Step 2: Dual Dummy cycles (SPEED=1, DIRECTION=0)                    */
    /* ------------------------------------------------------------------ */
    printf("\nStep 2: Dual Dummy cycles (SPEED=Dual, DIR=Dummy, LEN=7=8cycles, CSAAT=1)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = 7;       /* 8 dummy cycles */
    cmd.f.CSAAT = 1;     /* keep CS# low */
    cmd.f.SPEED = 1;     /* Dual */
    cmd.f.DIRECTION = 0; /* Dummy */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x (CMDINVAL=%u)\n", err_status.w, err_status.f.CMDINVAL);
    if (err_status.f.CMDINVAL) {
        printf("  FAIL: CMDINVAL for valid Dual Dummy command\n");
        pass = 0;
    } else {
        printf("  PASS: Dual Dummy accepted (no CMDINVAL)\n");
    }
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* ------------------------------------------------------------------ */
    /* Step 3: Dual RX (SPEED=1, DIRECTION=1)                              */
    /* ------------------------------------------------------------------ */
    printf("\nStep 3: Dual SPI RX (SPEED=Dual, DIR=RX, LEN=3=4bytes, CSAAT=0)\n");
    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    cmd.w = 0;
    cmd.f.LEN = 3;       /* 4 bytes */
    cmd.f.CSAAT = 0;     /* release CS# after */
    cmd.f.SPEED = 1;     /* Dual */
    cmd.f.DIRECTION = 1; /* RX */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_idle(TIMEOUT_LIMIT)) {
        printf("  FAIL: transaction did not complete (ACTIVE stuck)\n");
        pass = 0;
        goto done;
    }

    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  STATUS: RXQD=%u, RXEMPTY=%u, ACTIVE=%u\n", status.f.RXQD, status.f.RXEMPTY,
           status.f.ACTIVE);
    printf("  ERROR_STATUS=0x%08x (CMDINVAL=%u CSIDINVAL=%u)\n", err_status.w,
           err_status.f.CMDINVAL, err_status.f.CSIDINVAL);
    if (err_status.f.CMDINVAL || err_status.f.CSIDINVAL) {
        printf("  FAIL: CMD error for valid Dual RX command\n");
        pass = 0;
    } else if (status.f.RXQD < 1 || status.f.RXEMPTY) {
        /* RXQD is word count; 4-byte Dual RX packs into one RXDATA word */
        printf("  FAIL: Dual RX produced no data (RXQD=%u RXEMPTY=%u)\n", status.f.RXQD,
               status.f.RXEMPTY);
        pass = 0;
    } else {
        uint32_t rxdata = READ_REG(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
        printf("  RXDATA[0]: 0x%08x (4-byte Dual RX packed)\n", rxdata);
        printf("  PASS: Dual RX accepted (RXQD>=1, no CMDINVAL/CSIDINVAL)\n");
    }
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* SW_RST to drain the RX FIFO. The field is a level: confirm the drain while
     * it is held, then release, or the core stays in reset.
     * Wait for READY (not a blind spin) */
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
    int drained = wait_for_ready(TIMEOUT_LIMIT);
    status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    ctrl.f.SW_RST = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
    if (drained) {
        printf("  FAIL: READY not restored after SW_RST drain\n");
        pass = 0;
        goto done;
    }
    if (!status.f.RXEMPTY) {
        printf("  FAIL: RX FIFO not empty after SW_RST (RXQD=%u)\n", status.f.RXQD);
        pass = 0;
        goto done;
    }

    /* ------------------------------------------------------------------ */
    /* Step 4: CMDINVAL — DIRECTION=3 (bidirectional) at Dual speed        */
    /* ------------------------------------------------------------------ */
    printf("\nStep 4: CMDINVAL test (SPEED=Dual + DIRECTION=Bidirectional)\n");
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0x12345678);
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 1;     /* Dual */
    cmd.f.DIRECTION = 3; /* Bidirectional — invalid at Dual speed */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    /* Poll until CMDINVAL sticks (or timeout) — not a blind spin */
    {
        int t = TIMEOUT_LIMIT;
        while (t-- > 0) {
            err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
            if (err_status.f.CMDINVAL) break;
        }
        if (t < 0) {
            printf("  FAIL: timeout waiting for CMDINVAL sticky\n");
            pass = 0;
            goto done;
        }
    }
    if (!check_reg("CMDINVAL for Bidirectional+Dual", err_status.f.CMDINVAL, 1))
        pass = 0;
    else
        printf("  PASS: CMDINVAL detected for Bidirectional+Dual (expected)\n");

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    /* SW_RST to recover; hold, wait for READY, release */
    ctrl.w = READ_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
    drained = wait_for_ready(TIMEOUT_LIMIT);
    ctrl.f.SW_RST = 0;
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);
    if (drained) {
        printf("  FAIL: READY not restored after CMDINVAL SW_RST\n");
        pass = 0;
        goto done;
    }

    /* ------------------------------------------------------------------ */
    /* Step 5: Bidirectional accepted at Standard speed (SPEED=0)          */
    /* ------------------------------------------------------------------ */
    printf("\nStep 5: Bidirectional valid at Standard speed (SPEED=0, DIR=3)\n");
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFF);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    WRITE_REG(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xABCD1234);
    cmd.w = 0;
    cmd.f.LEN = 0;
    cmd.f.CSAAT = 0;
    cmd.f.SPEED = 0;     /* Standard */
    cmd.f.DIRECTION = 3; /* Bidirectional — valid at Standard speed */
    WRITE_REG(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd.w);

    if (wait_for_ready(TIMEOUT_LIMIT)) {
        pass = 0;
        goto done;
    }

    err_status.w = READ_REG(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    printf("  ERROR_STATUS=0x%08x (CMDINVAL=%u)\n", err_status.w, err_status.f.CMDINVAL);
    if (err_status.f.CMDINVAL) {
        printf("  FAIL: CMDINVAL for valid Standard Bidirectional command\n");
        pass = 0;
    } else {
        printf("  PASS: Standard Bidirectional accepted (no CMDINVAL)\n");
    }

done:
    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT DUAL SPI TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT DUAL SPI TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
