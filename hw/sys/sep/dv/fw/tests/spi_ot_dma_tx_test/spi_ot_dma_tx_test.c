/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SPI OT DMA TX Test - TC_SPIOT_016 (P1)
 *
 * Verifies SRAM-to-SPI TX FIFO transfer using DMA hardware handshake.
 * The Secure DMA reads from SRAM (incrementing source), writes to the
 * SPI TXDATA register (fixed destination, WRAP), triggered by
 * lsio_trigger_o when TX FIFO drops below the watermark.
 *
 * Signal path:
 *   spi_controller.lsio_trigger_o -> sep.lsio_trigger[0] -> secure_dma.lsio_trigger_i[0]
 *
 * Test Flow:
 *   1. Configure SPI mux for OpenTitan, enable SPI controller
 *   2. Configure SPI clock, watermarks, events
 *   3. Fill SRAM buffer with test pattern
 *   4. Configure Secure DMA: SRAM -> TXDATA with HW handshake
 *   5. Issue SPI CMD (TX direction) for N bytes
 *   6. Start DMA with HARDWARE_HANDSHAKE_ENABLE + GO
 *   7. Poll DMA STATUS for DONE or ERROR
 *   8. Verify no SPI errors, DMA completed
 *
 * Execution:
 *   make test-sep TEST_NAME=sep_spi_ot_dma_tx_test STACK=sim
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

#define DMA_TX_SIZE 64
#define DMA_CHUNK_SIZE 16 /* TX_WATERMARK * TRANSFER_WIDTH_BYTES: fills FIFO to WM, deasserts trigger */
#define CFG_TX_WATERMARK 4
#define CFG_RX_WATERMARK 1
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
    event_en.f.TXWM = 1;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, event_en.w);
}

static int configure_dma_for_spi_tx(uint32_t src_addr, uint32_t total_size, uint32_t chunk_size) {
    uint32_t cfg_regwen = READ_REG(OCH_SEP_TOP_SECURE_DMA_CFG_REGWEN_BASE_ADDR);
    if ((cfg_regwen & 0xF) != MUBI4_TRUE) {
        printf("  WARNING: DMA may be busy or locked (CFG_REGWEN=0x%x)\n", cfg_regwen);
    }

    /* Set up side effect region for DMA */
    __asm__ volatile("csrw 0x7c0, %0" : : "r"(0x8));

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src_addr);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR, 0x77);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, 0x2);

    /* SRC: increment (walk through SRAM), DST: wrap (fixed TXDATA register) */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR, 0x1);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR, 0x2);

    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total_size);
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, chunk_size);

    /* Enable hardware handshake from SPI trigger (bit 0).
     * lsio_trigger_o is FIFO-level-based (tx_wm), not interrupt-status-based,
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
    printf("SPI OT DMA TX Test (TC_SPIOT_016)\n");
    printf("========================================\n\n");

    int pass = 1;

    /* Step 1: SPI mux + controller init */
    spi_mux_select_ot();
    printf("SPI mux configured for OpenTitan\n");

    init_spi_controller();
    printf("SPI controller enabled: CLKDIV=%d, TX_WM=%d\n", SPI_CLKDIV, CFG_TX_WATERMARK);

    /* Step 2: Prepare SRAM test pattern */
    uint32_t src_base = OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + 0x4000;
    volatile uint32_t *src_ptr = (volatile uint32_t *)src_base;
    uint32_t num_words = DMA_TX_SIZE / 4;
    uint32_t i;

    printf("\nPreparing SRAM test pattern at 0x%08x (%u bytes)\n", src_base, DMA_TX_SIZE);
    for (i = 0; i < num_words; i++) {
        src_ptr[i] = 0xCA000000 | (i & 0xFF);
    }

    /* Verify pattern written */
    for (i = 0; i < num_words; i++) {
        if (src_ptr[i] != (0xCA000000 | (i & 0xFF))) {
            printf("  FAIL: SRAM pattern mismatch at word %u\n", i);
            pass = 0;
            break;
        }
    }
    printf("  SRAM pattern ready (%u words)\n", num_words);

    /* Step 3: Issue SPI CMD for TX direction */
    spi_controller__CMD_t cmd;
    cmd.w = 0;
    cmd.f.LEN = DMA_TX_SIZE - 1;
    cmd.f.DIRECTION = 2;
    cmd.f.SPEED = 0;
    cmd.f.CSAAT = 0;
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd.w);
    printf("SPI CMD issued: LEN=%u, DIRECTION=TX, SPEED=Standard\n", DMA_TX_SIZE - 1);

    /* Step 4: Configure and start DMA */
    printf("\nConfiguring DMA for SRAM->TXDATA transfer\n");
    int rc = configure_dma_for_spi_tx(src_base, DMA_TX_SIZE, DMA_CHUNK_SIZE);
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
    printf("  TXQD=%u, RXQD=%u, TXEMPTY=%u, ACTIVE=%u\n", spi_status.f.TXQD, spi_status.f.RXQD,
           spi_status.f.TXEMPTY, spi_status.f.ACTIVE);

    /* Check for SPI errors */
    spi_controller__ERROR_STATUS_CMDBUSY_610d1fb8_CMDINVAL_5f890e60_CSIDINVAL_52ab238c_OVERFLOW_b3d067e6_UNDERFLOW_cfe1cef2_t
        err_status;
    err_status.w = READ_REG(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err_status.w != 0) {
        printf("  SPI ERROR_STATUS=0x%08x\n", err_status.w);
        pass = 0;
    } else {
        printf("  No SPI errors\n");
    }

    /* Cleanup: disable handshake, restore defaults */
    WRITE_REG(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR,
              SECURE_DMA__HANDSHAKE_INTR_ENABLE_reset);
    WRITE_REG(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    printf("\n========================================\n");
    if (pass) {
        printf("=== SPI OT DMA TX TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== SPI OT DMA TX TEST FAILED ===\n");
        test_fail(0);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
    return pass ? 0 : -1;
}
