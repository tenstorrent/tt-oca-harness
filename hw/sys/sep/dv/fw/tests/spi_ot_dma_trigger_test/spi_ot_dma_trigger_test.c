/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT DMA Trigger Test
 *
 * Verifies the DMA trigger signal path (lsio_trigger_o) by exercising
 * TX/RX FIFO watermark conditions and confirming the Secure DMA
 * HANDSHAKE_INTR_ENABLE register is accessible for SPI trigger[0].
 *
 * lsio_trigger_o = tx_wm | rx_wm
 * tx_wm: asserted when TXQD < SPI_TX_WATERMARK (TX FIFO needs data)
 * rx_wm: asserted when RXQD >= SPI_RX_WATERMARK (RX FIFO has data)
 *
 * Test Flow:
 * 1. Enable controller
 * 2. Set SPI_TX_WATERMARK=4, verify STATUS.TXWM=1 (empty FIFO < 4)
 * 3. Write 8 words to TX FIFO, verify TXWM clears (TXQD >= 4)
 * 4. Drain via SW_RST, verify TXWM re-asserts
 * 5. Verify HANDSHAKE_INTR_ENABLE register write-readback
 * 6. Verify CLEAR_INTR_SRC register is writable
 * 7. Verify INTR_SRC_ADDR_0 register is writable
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

#define TIMEOUT_LIMIT 100000

static int check_reg(const char *name, uint32_t actual, uint32_t expected) {
    int ok = (actual == expected);
    printf("  %s: 0x%08x (expected 0x%08x) - %s\n", name, actual, expected, ok ? "PASS" : "FAIL");
    return ok;
}

/* Poll until SW_RST has drained TX (fail-closed). */
static int wait_for_tx_empty(int timeout) {
    spi_controller__STATUS_t status;
    while (timeout-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if (status.f.TXEMPTY && status.f.TXQD == 0 && !status.f.ACTIVE) return 0;
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  FAIL: TIMEOUT waiting for TXEMPTY after SW_RST (STATUS=0x%08x)\n", status.w);
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT DMA Trigger Test\n");
    printf("========================================\n\n");

    int pass = 1;
    spi_controller__CONTROL_t ctrl;
    spi_controller__STATUS_t status;
    uint32_t read_val;

    /* Enable controller with SPI_TX_WATERMARK=4 */
    ctrl.w = 0;
    ctrl.f.RX_WATERMARK = 1;
    ctrl.f.TX_WATERMARK = 4;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Configure clock */
    spi_controller__CONFIGOPTS_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = 9;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, cfg.w);

    /* Step 1: Verify TXWM when TX FIFO empty (TXQD=0 < SPI_TX_WATERMARK=4) */
    printf("\nStep 1: TXWM with empty FIFO (expect TXWM=1)\n");
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS=0x%08x, TXWM=%u, TXQD=%u, TXEMPTY=%u\n", status.w, status.f.TXWM,
           status.f.TXQD, status.f.TXEMPTY);
    if (status.f.TXWM != 1) {
        printf("  FAIL: TXWM should be 1 when TXQD < SPI_TX_WATERMARK\n");
        pass = 0;
    } else {
        printf("  PASS: TXWM=1 (trigger would fire for DMA TX refill)\n");
    }

    /* Step 2: Fill TX FIFO above watermark */
    printf("\nStep 2: Fill TX FIFO above watermark (write 8 words)\n");
    uint32_t i;
    for (i = 0; i < 8; i++) {
        WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xA0000000 | i);
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  STATUS=0x%08x, TXWM=%u, TXQD=%u\n", status.w, status.f.TXWM, status.f.TXQD);
    if (status.f.TXWM != 0) {
        printf("  FAIL: TXWM still 1 after 8 writes (TXQD=%u, expected TXWM=0)\n", status.f.TXQD);
        pass = 0;
    } else {
        printf("  PASS: TXWM=0 (TXQD >= SPI_TX_WATERMARK, trigger deasserted)\n");
    }

    /* Step 3: SW_RST to drain, verify TXWM re-asserts */
    printf("\nStep 3: SW_RST drain, verify TXWM re-asserts\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    ctrl.f.SW_RST = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    /* Sample the drained state while SW_RST is held, then release it: the field
     * is a level and the core stays in reset until it is cleared. */
    if (wait_for_tx_empty(TIMEOUT_LIMIT)) {
        pass = 0;
    }
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    ctrl.f.SW_RST = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl.w);

    printf("  After SW_RST: TXWM=%u, TXQD=%u, TXEMPTY=%u\n", status.f.TXWM, status.f.TXQD,
           status.f.TXEMPTY);
    if (status.f.TXEMPTY != 1 || status.f.TXQD != 0) {
        printf("  FAIL: expected TXEMPTY=1 TXQD=0 after SW_RST drain\n");
        pass = 0;
    } else if (status.f.TXWM != 1) {
        printf("  FAIL: TXWM should re-assert after drain (TXQD < TX_WATERMARK=4)\n");
        pass = 0;
    } else {
        printf("  PASS: TXWM=1 after SW_RST drain (TXQD=0)\n");
    }

    /* Step 4: Verify RX watermark field */
    printf("\nStep 4: SPI_RX_WATERMARK configuration\n");
    ctrl.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    if (!check_reg("SPI_RX_WATERMARK readback", ctrl.f.RX_WATERMARK, 1)) pass = 0;

    /* Re-read STATUS for RXWM (empty RX FIFO, RXQD=0 < SPI_RX_WATERMARK=1) */
    status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("  RXWM=%u, RXQD=%u, RXEMPTY=%u (RXWM=0 expected: RXQD < threshold)\n", status.f.RXWM,
           status.f.RXQD, status.f.RXEMPTY);
    if (status.f.RXEMPTY != 1 || status.f.RXQD != 0) {
        printf("  FAIL: expected empty RX FIFO (RXEMPTY=1, RXQD=0)\n");
        pass = 0;
    } else if (status.f.RXWM != 0) {
        printf("  FAIL: RXWM should be 0 when RXQD < RX_WATERMARK\n");
        pass = 0;
    } else {
        printf("  PASS: RXWM=0 with empty RX FIFO\n");
    }

    /* Step 5: DMA HANDSHAKE_INTR_ENABLE register */
    printf("\nStep 5: DMA HANDSHAKE_INTR_ENABLE register access\n");
    read_val = READ_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR);
    printf("  Default: 0x%08x\n", read_val);

    /* Enable bit 0 for SPI trigger */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    read_val = READ_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("HANDSHAKE_INTR_ENABLE[0]=1", read_val & 0x1, 0x1)) pass = 0;

    /* Disable all */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x0);
    read_val = READ_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR);
    if (!check_reg("HANDSHAKE_INTR_ENABLE=0", read_val, 0x0)) pass = 0;

    /* Restore default */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR,
              SECURE_DMA__HANDSHAKE_INTR_ENABLE__MASK_reset);

    /* Step 6: DMA CLEAR_INTR_SRC register */
    printf("\nStep 6: DMA CLEAR_INTR_SRC register access\n");
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CLEAR_INTR_SRC_BASE_ADDR, 0x1);
    read_val = READ_REG(OCH_SEP_TOP_SECURE_DMA_CLEAR_INTR_SRC_BASE_ADDR);
    if (!check_reg("CLEAR_INTR_SRC readback", read_val, 0x1)) pass = 0;

    /* Step 7: DMA INTR_SRC_ADDR_0 register (configure source address for handshake) */
    printf("\nStep 7: DMA INTR_SRC_ADDR_0 register\n");
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_INTR_SRC_ADDR_0_BASE_ADDR(0),
              OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR);
    read_val = READ_REG(OCH_SEP_TOP_SECURE_DMA_INTR_SRC_ADDR_0_BASE_ADDR(0));
    if (!check_reg("INTR_SRC_ADDR_0", read_val, OCH_SEP_TOP_SPI_CONTROLLER_INTR_STATE_BASE_ADDR))
        pass = 0;

    /* Step 8: EVENT_ENABLE for DMA trigger path */
    printf("\nStep 8: SPI EVENT_ENABLE for DMA trigger events\n");
    spi_controller__EVENT_ENABLE_t event_en;
    event_en.w = 0;
    event_en.f.TXWM = 1;
    event_en.f.RXWM = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_en.w);
    event_en.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!check_reg("TXWM event enabled", event_en.f.TXWM, 1)) pass = 0;
    if (!check_reg("RXWM event enabled", event_en.f.RXWM, 1)) pass = 0;

    /* Cleanup */
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT DMA TRIGGER TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT DMA TRIGGER TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
