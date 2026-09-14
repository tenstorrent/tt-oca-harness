/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT Watermark Test
 *
 * Verifies TX and RX watermark configuration and status bit transitions.
 *
 * CTRL register watermark fields:
 * CTRL[7:0]  = RX_WATERMARK (8-bit): RXWM=1 when RXQD > RX_WATERMARK
 * CTRL[15:8] = TX_WATERMARK (8-bit): TXWM=1 when TXQD < TX_WATERMARK
 *
 * Default: CTRL_REG_DEFAULT=0x7F → RX_WM=0x7F=127, TX_WM=0x00=0
 * - Default TXWM=0 (TXQD=0 is not < 0)
 * - Default RXWM=0 (RXQD=0 is not > 127)
 *
 * Test Flow:
 * 1. Verify default watermarks (RX_WM=127, TX_WM=0), TXWM=0, RXWM=0
 * 2. Set TX_WM=1: TXWM=1 (empty FIFO: TXQD=0 < 1)
 * 3. Write 2 words to TX FIFO: TXWM=0 (TXQD=2 >= 1)
 * 4. Set TX_WM=4: TXWM=1 (TXQD=2 < 4)
 * 5. Write 2 more words (TXQD=4): TXWM=0 (TXQD=4 >= 4)
 * 6. Set TX_WM=0: TXWM=0 always (0 < 0 is false)
 * 7. Verify RX_WM write-readback (min=0, max=0xFF, restore default)
 * 8. SW_RST to drain TX FIFO
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT Watermark Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CTRL_t ctrl;
    spi_controller__STATUS_t status;

    /* Enable controller with defaults (TX_WM=0, RX_WM=127) */
    ctrl.w = SPI_CONTROLLER__CTRL_reset;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    /* ------------------------------------------------------------------ */
    /* Step 1: Verify default watermarks                                   */
    /* ------------------------------------------------------------------ */
    printf("Step 1: Default watermark values\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    printf("  CTRL=0x%08x: TX_WM=%u, RX_WM=%u\n", ctrl.w, ctrl.f.TX_WATERMARK, ctrl.f.RX_WATERMARK);
    if (ctrl.f.TX_WATERMARK != SPI_CONTROLLER__CTRL__TX_WATERMARK_reset) {
        printf("  FAIL: Default TX_WM expected %u, got %u\n",
               SPI_CONTROLLER__CTRL__TX_WATERMARK_reset, ctrl.f.TX_WATERMARK);
        pass = 0;
    } else {
        printf("  PASS: Default TX_WM=%u\n", SPI_CONTROLLER__CTRL__TX_WATERMARK_reset);
    }
    if (ctrl.f.RX_WATERMARK != SPI_CONTROLLER__CTRL__RX_WATERMARK_reset) {
        printf("  FAIL: Default RX_WM expected %u, got %u\n",
               SPI_CONTROLLER__CTRL__RX_WATERMARK_reset, ctrl.f.RX_WATERMARK);
        pass = 0;
    } else {
        printf("  PASS: Default RX_WM=%u\n", SPI_CONTROLLER__CTRL__RX_WATERMARK_reset);
    }

    /* Verify STATUS bits with default watermarks (TX/RX FIFOs empty) */
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf(
        "  STATUS: TXWM=%u (expected 0: TXQD=0 not < 0), RXWM=%u (expected 0: RXQD=0 not > 127)\n",
        status.f.TXWM, status.f.RXWM);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM should be 0 with TX_WM=0\n");
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 correct with TX_WM=0\n");
    }
    if (status.f.RXWM != 0) {
        printf("  FAIL: RXWM should be 0 with RXQD=0 and RX_WM=%u\n",
               SPI_CONTROLLER__CTRL__RX_WATERMARK_reset);
        pass = 0;
    } else {
        printf("  PASS: RXWM=0 correct with empty RX FIFO\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 2: Set TX_WM=1: TXWM=1 (TXQD=0 < TX_WM=1)                    */
    /* ------------------------------------------------------------------ */
    printf("\nStep 2: Set TX_WM=1, verify TXWM=1 (TX FIFO below watermark)\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.TX_WATERMARK = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TX_WM=1, TXQD=%u → TXWM=%u (expected 1)\n", status.f.TXQD, status.f.TXWM);
    if (status.f.TXWM != 1) {
        printf("  FAIL: TXWM should be 1 (TXQD=%u < TX_WM=1)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=1 correct (TX FIFO needs filling)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 3: Write 2 words to TX FIFO: TXWM=0 (TXQD=2 >= TX_WM=1)      */
    /* ------------------------------------------------------------------ */
    printf("\nStep 3: Write 2 words to TX FIFO, verify TXWM=0\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0xAABBCCDD);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x11223344);

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TX_WM=1, TXQD=%u → TXWM=%u (expected 0)\n", status.f.TXQD, status.f.TXWM);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM should be 0 (TXQD=%u >= TX_WM=1)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 correct (TX FIFO above watermark)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 4: Raise TX_WM to 4: TXWM=1 (TXQD=2 < TX_WM=4)              */
    /* ------------------------------------------------------------------ */
    printf("\nStep 4: Set TX_WM=4, verify TXWM=1 (TXQD=2 < 4)\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.TX_WATERMARK = 4;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TX_WM=4, TXQD=%u → TXWM=%u (expected 1)\n", status.f.TXQD, status.f.TXWM);
    if (status.f.TXWM != 1) {
        printf("  FAIL: TXWM should be 1 (TXQD=%u < TX_WM=4)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=1 correct (watermark raised above TXQD)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 5: Write 2 more words (TXQD→4): TXWM=0 (TXQD=4 >= TX_WM=4)  */
    /* ------------------------------------------------------------------ */
    printf("\nStep 5: Write 2 more words (TXQD→4), verify TXWM=0\n");
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x55667788);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, 0x99AABBCC);

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TX_WM=4, TXQD=%u → TXWM=%u (expected 0)\n", status.f.TXQD, status.f.TXWM);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM should be 0 (TXQD=%u >= TX_WM=4)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 correct (TXQD meets watermark)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 6: Set TX_WM=0: TXWM=0 always (TXQD < 0 is impossible)       */
    /* ------------------------------------------------------------------ */
    printf("\nStep 6: Set TX_WM=0, verify TXWM=0 (threshold disabled)\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.TX_WATERMARK = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  TX_WM=0, TXQD=%u → TXWM=%u (expected 0)\n", status.f.TXQD, status.f.TXWM);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM should be 0 with TX_WM=0 (no threshold)\n");
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 correct (watermark disabled)\n");
    }

    /* ------------------------------------------------------------------ */
    /* Step 7: RX_WM write-readback verification (min=0, max=0xFF)         */
    /* ------------------------------------------------------------------ */
    printf("\nStep 7: RX_WM write-readback (min=0, max=0xFF, restore)\n");
    /* min: RX_WM=0 */
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.RX_WATERMARK = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    printf("  RX_WM=0 readback: %u\n", ctrl.f.RX_WATERMARK);
    if (ctrl.f.RX_WATERMARK != 0) {
        printf("  FAIL: RX_WM=0 readback failed\n");
        pass = 0;
    } else {
        printf("  PASS: RX_WM=0 readback OK\n");
    }

    /* max: RX_WM=0xFF */
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.RX_WATERMARK = 0xFF;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    printf("  RX_WM=0xFF readback: 0x%02x\n", ctrl.f.RX_WATERMARK);
    if (ctrl.f.RX_WATERMARK != 0xFF) {
        printf("  FAIL: RX_WM=0xFF readback failed\n");
        pass = 0;
    } else {
        printf("  PASS: RX_WM=0xFF readback OK\n");
    }

    /* Restore default RX_WM from generated field reset */
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.RX_WATERMARK = SPI_CONTROLLER__CTRL__RX_WATERMARK_reset;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    /* ------------------------------------------------------------------ */
    /* Step 8: SW_RST to drain TX FIFO                                     */
    /* ------------------------------------------------------------------ */
    printf("\nStep 8: SW_RST to drain TX FIFO\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);
    {
        int t = TIMEOUT_LIMIT;
        while (t-- > 0) {
            status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
            if (status.f.TXEMPTY && status.f.TXQD == 0 && !status.f.ACTIVE) break;
        }
        if (t <= 0) {
            printf("  FAIL: TIMEOUT waiting for TXEMPTY after SW_RST (STATUS=0x%08x)\n", status.w);
            pass = 0;
        }
    }

    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  After SW_RST: TXEMPTY=%u, TXQD=%u\n", status.f.TXEMPTY, status.f.TXQD);
    if (!status.f.TXEMPTY || status.f.TXQD != 0) {
        printf("  FAIL: TXEMPTY should be 1 and TXQD=0 after SW_RST\n");
        pass = 0;
    } else {
        printf("  PASS: TX FIFO drained by SW_RST\n");
    }

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT WATERMARK TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT WATERMARK TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
