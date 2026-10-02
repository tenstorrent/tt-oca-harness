// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan SPI RX -> Secure DMA -> SRAM firmware test. The EL2 CPU
// configures the OpenTitan SPI host, arms the Secure DMA in hardware-handshake
// mode (source: the fixed SPI receive data register; destination: incrementing
// SRAM), then issues a flash read. Each time the SPI RX FIFO crosses its
// watermark, the controller raises its DMA trigger and the DMA drains one chunk
// into SRAM:
//
//   spi_host.lsio_trigger_o -> sep.lsio_trigger[0] -> secure_dma.lsio_trigger_i[0]
//
// This whole datapath is internal to bare `sep`. Handshake index 0 is the
// stimulus: on any other index the DMA gets no trigger, never reaches DONE, and
// the test fails.
//
// The testbench preloads the flash model with a known byte, so every
// DMA-written SRAM word is value-checked, which proves the data path and not
// only completion. The test also checks that the DMA status bits clear on a
// write-one-to-clear.
//
// main() returns the error count; crt0.s turns it into the pass/fail mailbox
// word that the boot scoreboard gates on.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"
#include "sep_spi.h"

#define RX_SIZE 64u // bytes to receive (multiple of 4)
#define RX_WORDS (RX_SIZE / 4u)
#define DMA_CHUNK 16u   // one chunk drains the FIFO below the watermark
#define RX_WATERMARK 4u // RX FIFO words that raise the DMA trigger
#define DST_STAGING_OFF 0x6000u
#define DST_ADDR ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR + DST_STAGING_OFF)
#define RX_PATTERN 0xA5u        // flash byte the testbench preloads
#define EXPECT_WORD 0xA5A5A5A5u // 4 x RX_PATTERN, packing-agnostic
#define FILL_WORD 0xDEADBEEFu   // pre-DMA SRAM marker
#define SPI_READ_OPCODE 0x03u   // NOR-flash READ (1-1-1), 24-bit addr
#define DMA_STATUS_RW1C_MASK \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)

#define DMA_POLL_TIMEOUT 200000
#define SPI_POLL_TIMEOUT 200000

int main(void) {
    int errors = 0;

    /* Staging offset must stay inside the generated SEP SRAM aperture. */
    if (DST_STAGING_OFF + RX_SIZE > (uint32_t)SEP_TOP_SEP_SRAM_SIZE) {
        sep_mbx_puts("FAIL: DST staging offset outside SEP SRAM\n");
        return 1;
    }

    sep_outbound_filter_init(); // open mailbox window (STDOUT via generated filter map)
    sep_mbx_puts("SEP SPI OT DMA RX test\n");
    sep_mbx_puts("STEP filter init done; flash model preloaded by the host\n");

    // --- OpenTitan SPI host init ---------------------------------------------
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           (RX_WATERMARK << SPI_CONTROLLER__CONTROL__RX_WATERMARK_bp) |
               SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm | SPI_CONTROLLER__CONTROL__SPIEN_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    sep_mbx_puts("STEP SPI host configured: RX watermark, clock divider, enable\n");
    spi_wr(SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, SPI_CONTROLLER__EVENT_ENABLE__RXWM_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR,
           0xFFFFFFFFu); // clear any sticky error
    if (spi_wait_ready(SPI_POLL_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: SPI host not ready\n");
        return 1;
    }

    // --- Clear the SRAM destination ------------------------------------------
    volatile uint32_t *dst = (volatile uint32_t *)DST_ADDR;
    for (uint32_t i = 0; i < RX_WORDS; i++) {
        dst[i] = FILL_WORD;
    }

    // --- Arm the Secure DMA: RXDATA (fixed/WRAP) -> SRAM (incrementing) -------
    // Hardware handshake from the SPI DMA trigger. The trigger follows the FIFO
    // level, so no interrupt-source clear is needed (the CTN clear bus is tied
    // off in bare sep and would hang).
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, SECURE_DMA__RANGE_VALID__RANGE_VALID_bm);
    sep_mbx_puts("STEP DMA armed: RXDATA(WRAP) -> SRAM(INCR), hardware handshake\n");
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR,
               SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, DST_ADDR);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
               SEP_DMA_ASID_PAIR(SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset,
                                 SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset));
    sep_dma_wr(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR,
               SECURE_DMA__SRC_CONFIG__WRAP_bm); // fixed RXDATA register
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR,
               SECURE_DMA__DST_CONFIG__INCREMENT_bm); // walk through SRAM
    sep_dma_wr(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, RX_SIZE);
    sep_dma_wr(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, DMA_CHUNK);
    sep_dma_wr(SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    sep_dma_wr(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
               SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                   SECURE_DMA__CONTROL__HARDWARE_HANDSHAKE_ENABLE_bm | SEP_DMA_OPCODE_COPY);

    // --- Issue the SPI flash READ --------------------------------------------
    // The TX segment sends the opcode and a zero 24-bit address, low byte
    // first, with CS held; the RX segment clocks in RX_SIZE bytes and releases
    // CS. The flash model streams its preloaded bytes back.
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), SPI_READ_OPCODE);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           (SPI_CMD_DIR_TX << SPI_CONTROLLER__COMMAND__DIRECTION_bp) |
               SPI_CONTROLLER__COMMAND__CSAAT_bm | ((4u - 1u) << SPI_CONTROLLER__COMMAND__LEN_bp));
    if (spi_wait_ready(SPI_POLL_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: SPI host stuck after command phase\n");
        errors++;
    }
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           (SPI_CMD_DIR_RX << SPI_CONTROLLER__COMMAND__DIRECTION_bp) |
               ((RX_SIZE - 1u) << SPI_CONTROLLER__COMMAND__LEN_bp));
    sep_mbx_puts("STEP flash READ issued: opcode 0x03 + 24-bit address\n");

    // --- Wait for the DMA to drain all chunks --------------------------------
    uint32_t status_before_clear = 0;
    int timeout = DMA_POLL_TIMEOUT;
    while (timeout-- > 0) {
        status_before_clear = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (status_before_clear & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) {
            break;
        }
    }
    if (!(status_before_clear & SECURE_DMA__STATUS__DONE_bm)) {
        sep_mbx_puts("FAIL: DMA did not complete\n");
        errors++;
    }
    if (status_before_clear & SECURE_DMA__STATUS__ERROR_bm) {
        sep_mbx_puts("FAIL: DMA reported error\n");
        errors++;
    }
    if (sep_dma_rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR) != 0) {
        sep_mbx_puts("FAIL: DMA error code set\n");
        errors++;
    }

    // --- RW1C status-clear proof ---------------------------------------------
    // Write one to the status bits and check that they read back clear.
    sep_dma_wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, DMA_STATUS_RW1C_MASK);
    __asm__ volatile("fence" ::: "memory");
    uint32_t status_after_clear = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    sep_mbx_puts("STEP DMA polled to completion; status write-one-to-clear applied\n");
    if (status_after_clear & DMA_STATUS_RW1C_MASK) {
        sep_mbx_puts("FAIL: DMA STATUS RW1C bits did not clear\n");
        errors++;
    }

    // --- SPI controller must be clean ----------------------------------------
    int spi_idle = (spi_wait_idle(SPI_POLL_TIMEOUT) == 0);
    if (!spi_idle) {
        sep_mbx_puts("FAIL: SPI host stuck active\n");
        errors++;
    }
    uint32_t spi_err_status = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (spi_err_status != 0) {
        sep_mbx_puts("FAIL: SPI error status set\n");
        errors++;
    }

    // Log the values behind the checks above, so a pass is auditable.
    sep_mbx_puts("CHK-NOERR: dma_status=");
    sep_mbx_puthex(status_after_clear);
    sep_mbx_puts(" dma_err_code=");
    sep_mbx_puthex(sep_dma_rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
    sep_mbx_puts(" spi_idle=");
    sep_mbx_putc(spi_idle ? '1' : '0');
    sep_mbx_puts(" spi_err_status=");
    sep_mbx_puthex(spi_err_status);
    sep_mbx_putc('\n');

    // --- Value-check the received data ---------------------------------------
    // The flash model preloads RX_PATTERN across the read window, so
    // EXPECT_WORD is the only acceptable result. Do not accept all-ones: the
    // idle receive line, the model's unprogrammed store and an unrecognised
    // opcode all read as ones, so all-ones is the signature of a broken RX path.
    {
        uint32_t w0 = dst[0];
        int ok_pattern = (w0 == EXPECT_WORD);
        for (uint32_t i = 0; i < RX_WORDS; i++) {
            if (!ok_pattern || dst[i] != w0) {
                if (!ok_pattern) {
                    sep_mbx_puts("FAIL: SRAM pattern wrong (expect 0xA5A5A5A5)\n");
                } else {
                    sep_mbx_puts("FAIL: SRAM window not uniform (partial transfer)\n");
                }
                errors++;
                break;
            }
        }
    }

    // --- Cleanup -------------------------------------------------------------
    sep_dma_wr(SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x0);
    spi_wr(SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    if (errors == 0) {
        sep_mbx_puts("PASS: SPI RX FIFO -> DMA -> SRAM (0xA5) + RW1C verified\n");
    }
    return errors;
}
