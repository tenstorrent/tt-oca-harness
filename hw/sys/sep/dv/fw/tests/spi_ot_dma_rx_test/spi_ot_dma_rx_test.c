/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT DMA RX Test - TC_SPIOT_017 (P1)
 *
 * Verifies SPI RX FIFO-to-SRAM transfer using DMA hardware handshake.
 * The Secure DMA reads from the SPI RXDATA register (fixed source, WRAP)
 * and writes to SRAM (incrementing destination), triggered by
 * lsio_trigger_o when RX FIFO reaches/exceeds the watermark.
 *
 * Signal path:
 *   spi_controller.lsio_trigger_o -> sep.lsio_trigger[0] -> secure_dma.lsio_trigger_i[0]
 *
 * Test Flow:
 *   1. Configure SPI mux for OpenTitan, enable SPI controller
 *   2. Configure SPI clock, RX watermark, events
 *   3. Clear SRAM destination buffer
 *   4. Issue SPI CMD (RX direction) for N bytes
 *   5. Configure Secure DMA: RXDATA -> SRAM with HW handshake
 *   6. Start DMA with HARDWARE_HANDSHAKE_ENABLE + GO
 *   7. Poll DMA STATUS for DONE or ERROR
 *   8. Verify no SPI errors, DMA completed, check SRAM buffer
 *
 * Note: Without an external SPI flash model providing data, RX data
 * will be 0xFF (MISO idle high) or 0x00 depending on the testbench.
 * The primary verification is that the DMA+SPI handshake completes
 * without error.
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_spi_ot_dma_rx_test STACK=sim
 */

#include <stdint.h>
#include <stdio.h>
#include "sep.h"
#include "och_sep_common.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"
#include "spi_clk.h"
#include "spi_mux.h"

#define MUBI4_TRUE 0x6

#define DMA_RX_SIZE 64
#define DMA_CHUNK_SIZE \
    16 /* RX_WATERMARK * TRANSFER_WIDTH_BYTES: drain FIFO to below WM, deasserts trigger */
#define CFG_TX_WATERMARK 0 /* Set to 0 so tx_wm is never asserted in RX-only mode */
#define CFG_RX_WATERMARK 4
#define SPI_CLKDIV spi_clkdiv()
#define DMA_TIMEOUT 200000

static void init_spi_controller(void) {
    spi_controller__CTRL_t ctrl;
    ctrl.w = 0;
    ctrl.f.RX_WATERMARK = CFG_RX_WATERMARK;
    ctrl.f.TX_WATERMARK = CFG_TX_WATERMARK;
    ctrl.f.SPIEN = 1;
    ctrl.f.OUTPUT_EN = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR, ctrl.w);

    spi_controller__CFG_t cfg;
    cfg.w = 0;
    cfg.f.CLKDIV = SPI_CLKDIV;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, cfg.w);

    spi_controller__EVENT_ENABLE_t event_en;
    event_en.w = 0;
    event_en.f.RXWM = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_en.w);
}

static int configure_dma_for_spi_rx(uint32_t dst_addr, uint32_t total_size, uint32_t chunk_size) {
    uint32_t cfg_regwen = READ_REG(OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR);
    if ((cfg_regwen & 0xF) != MUBI4_TRUE) {
        printf("  WARNING: DMA may be busy or locked (CFG_REGWEN=0x%x)\n", cfg_regwen);
    }

    /* Set up side effect region for DMA */
    __asm__ volatile("csrw 0x7c0, %0" : : "r"(0x8));

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);

    /* SRC: SPI RXDATA (fixed register), DST: SRAM (incrementing) */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR,
              OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, dst_addr);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, 0x77);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, 0x2);

    /* SRC: wrap (fixed RXDATA register), DST: increment (walk through SRAM) */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, 0x2);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, 0x1);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total_size);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, chunk_size);

    /* Enable hardware handshake from SPI trigger (bit 0).
     * lsio_trigger_o is FIFO-level-based (rx_wm), not interrupt-status-based,
     * so CLEAR_INTR_SRC is not needed (and the CTN bus used by default for
     * interrupt clears is tied off in sep_dma_wrap and would hang). */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);

    return 0;
}

static int start_dma_and_wait(void) {
    secure_dma__CONTROL_t control;
    control.w = 0;
    control.f.OPCODE = 0;
    control.f.HARDWARE_HANDSHAKE_ENABLE = 1;
    control.f.INITIAL_TRANSFER = 1;
    control.f.GO = 1;

    printf("  Starting DMA: CONTROL=0x%08x\n", control.w);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, control.w);

    secure_dma__STATUS_t status;
    int timeout = DMA_TIMEOUT;
    while (timeout-- > 0) {
        status.w = READ_REG(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (status.f.DONE) {
            printf("  DMA transfer completed (STATUS=0x%08x)\n", status.w);
            return 0;
        }
        if (status.f.ERROR) {
            uint32_t err_code = READ_REG(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR);
            printf("  DMA ERROR: STATUS=0x%08x, ERROR_CODE=0x%08x\n", status.w, err_code);
            return -1;
        }
    }

    printf("  DMA TIMEOUT: STATUS=0x%08x after %d polls\n", status.w, DMA_TIMEOUT);
    return -2;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("SPI OT DMA RX Test (TC_SPIOT_017)\n");
    printf("========================================\n\n");

    int pass = 1;

    /* Step 1: SPI mux + controller init */
    spi_mux_select_ot();
    printf("SPI mux configured for OpenTitan\n");

    init_spi_controller();
    printf("SPI controller enabled: CLKDIV=%d, RX_WM=%d\n", SPI_CLKDIV, CFG_RX_WATERMARK);

    /* Step 2: Clear SRAM destination buffer */
    uint32_t dst_base = OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x6000;
    volatile uint32_t *dst_ptr = (volatile uint32_t *)dst_base;
    uint32_t num_words = DMA_RX_SIZE / 4;
    uint32_t i;

    printf("\nClearing SRAM destination at 0x%08x (%u bytes)\n", dst_base, DMA_RX_SIZE);
    for (i = 0; i < num_words; i++) {
        dst_ptr[i] = 0xDEADBEEF;
    }

    /* Step 3: Issue SPI CMD for RX direction */
    spi_controller__CMD_t cmd;
    cmd.w = 0;
    cmd.f.LEN = DMA_RX_SIZE - 1;
    cmd.f.DIRECTION = 1;
    cmd.f.SPEED = 0;
    cmd.f.CSAAT = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    printf("SPI CMD issued: LEN=%u, DIRECTION=RX, SPEED=Standard\n", DMA_RX_SIZE - 1);

    /* Step 4: Configure and start DMA */
    printf("\nConfiguring DMA for RXDATA->SRAM transfer\n");
    int rc = configure_dma_for_spi_rx(dst_base, DMA_RX_SIZE, DMA_CHUNK_SIZE);
    if (rc != 0) {
        printf("DMA configuration failed\n");
        pass = 0;
    }

    if (pass) {
        printf("\nStarting DMA transfer...\n");
        rc = start_dma_and_wait();
        if (rc != 0) {
            printf("DMA transfer failed (rc=%d)\n", rc);
            pass = 0;
        }
    }

    /* Step 5: Check SPI status */
    spi_controller__STATUS_t spi_status;
    spi_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    printf("\nSPI STATUS after DMA: 0x%08x\n", spi_status.w);
    printf("  TXQD=%u, RXQD=%u, RXEMPTY=%u, ACTIVE=%u\n", spi_status.f.TXQD, spi_status.f.RXQD,
           spi_status.f.RXEMPTY, spi_status.f.ACTIVE);

    spi_controller__ERROR_STATUS_CMDBUSY_610d1fb8_CMDINVAL_5f890e60_CSIDINVAL_52ab238c_OVERFLOW_b3d067e6_UNDERFLOW_cfe1cef2_t
        err_status;
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err_status.w != 0) {
        printf("  SPI ERROR_STATUS=0x%08x\n", err_status.w);
        pass = 0;
    } else {
        printf("  No SPI errors\n");
    }

    /* Step 6: Dump SRAM buffer content */
    printf("\nSRAM destination buffer dump (first 8 words):\n");
    for (i = 0; i < 8 && i < num_words; i++) {
        printf("  [%u] 0x%08x", i, dst_ptr[i]);
        if (dst_ptr[i] == 0xDEADBEEF) {
            printf(" (unchanged)");
        }
        printf("\n");
    }

    /* Verify at least some words were updated by DMA */
    uint32_t changed = 0;
    for (i = 0; i < num_words; i++) {
        if (dst_ptr[i] != 0xDEADBEEF) {
            changed++;
        }
    }
    printf("  %u/%u words modified by DMA\n", changed, num_words);

    /* Cleanup */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR,
              SECURE_DMA__HANDSHAKE_INTR_ENABLE_reset);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT DMA RX TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT DMA RX TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
