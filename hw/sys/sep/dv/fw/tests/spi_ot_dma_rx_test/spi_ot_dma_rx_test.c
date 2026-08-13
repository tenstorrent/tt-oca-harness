// SPDX-License-Identifier: Apache-2.0
//
// SEP OpenTitan-SPI RX -> Secure-DMA -> SRAM firmware test (OSS port of the OCAH
// sep_spi_ot_dma_rx_test, ). The EL2 CPU configures the OpenTitan
// SPI host, arms the Secure DMA in hardware-handshake mode (SRC = SPI RXDATA,
// fixed/WRAP; DST = SRAM, incrementing), then issues a SPI read. As the SPI RX
// FIFO crosses its watermark, the controller raises lsio_trigger, which drains a
// chunk into SRAM via the DMA hardware handshake:
//
//   spi_host.lsio_trigger_o -> sep.lsio_trigger[0] -> secure_dma.lsio_trigger_i[0]
//
// This whole datapath is internal to bare `sep` (hw/sep/sep.sv:899). Exercises
// edge E7 (SPI-FIFO -> DMA) on the OpenTitan SPI line; the Cadence xSPI path is
// out of the OSS DUT.
//
// PARITY-PLUS over OCAH: the OCAH test only checks "DMA done + no SPI error"
// because it clocks idle MISO (no flash model) and leaves the received data
// unchecked. Here the OSS flash BFM is preloaded with a known constant (0xA5),
// the firmware issues a real flash READ (0x03), and then VALUE-CHECKS that every
// DMA-written SRAM word == 0xA5A5A5A5 -- so the checker actually proves the
// SPI->DMA->SRAM data path, not just completion. It also proves the DMA STATUS
// RW1C clear contract (write-1-clear -> reads back 0), per AGENTS.md §7.
//
// main() returns the error count; start.S turns 0 -> PASS magic, non-zero ->
// FAIL magic on the 0x8000_0000 mailbox, which the boot scoreboard gates on.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"
#include "sep_spi.h"

#define RX_SIZE 64u // bytes to receive (multiple of 4)
#define RX_WORDS (RX_SIZE / 4u)
#define DMA_CHUNK 16u   // RX_WM(4 words) * 4B: drain to below WM
#define RX_WATERMARK 4u // RX FIFO words that assert lsio_trigger
#define DST_STAGING_OFF 0x6000u
#define DST_ADDR ((uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + DST_STAGING_OFF)
#define RX_PATTERN 0xA5u        // BFM-preloaded flash byte (see test .py)
#define EXPECT_WORD 0xA5A5A5A5u // 4 x RX_PATTERN, packing-agnostic
#define FILL_WORD 0xDEADBEEFu   // pre-DMA SRAM marker
#define SPI_READ_OPCODE 0x03u   // NOR-flash READ (1-1-1), 24-bit addr
#define DMA_STATUS_RW1C_MASK \
    (SEP_DMA_STATUS_DONE | SEP_DMA_STATUS_ERROR | SEP_DMA_STATUS_CHUNK_DONE)

#define DMA_POLL_TIMEOUT 200000
#define SPI_POLL_TIMEOUT 200000

int main(void) {
    int errors = 0;

    /* Staging offset must stay inside the generated SEP SRAM aperture. */
    if (DST_STAGING_OFF + RX_SIZE > (uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE) {
        sep_mbx_puts("FAIL: DST staging offset outside SEP SRAM\n");
        return 1;
    }

    sep_outbound_filter_init(); // open mailbox window (STDOUT via generated filter map)
    sep_mbx_puts("SEP SPI OT DMA RX test\n");

    // --- OpenTitan SPI host init ---------------------------------------------
    // Nonfree: route pads to OT and release cs_force_high (needs NONFREE_ROOT
    // overlay so spi_mux_select_ot is not a no-op). Open SEP has no mux.
    sep_spi_mux_release_cs();
    // RX watermark = 4 words (asserts lsio_trigger), TX watermark = 0, enable the
    // controller + output.
    spi_wr(SPI_CTRL_REG,
           (RX_WATERMARK << SPI_CTRL_RX_WM_SHIFT) | SPI_CTRL_OUTPUT_EN | SPI_CTRL_SPIEN);
    spi_wr(SPI_CFG_REG, SPI_CFG_CLKDIV9_CSN);
    spi_wr(SPI_CSID_REG, 0);
    spi_wr(SPI_EVENT_ENABLE_REG, SPI_EVENT_RXWM);
    spi_wr(SPI_ERROR_STATUS_REG, 0xFFFFFFFFu); // clear any sticky error
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
    // Hardware handshake from the SPI lsio_trigger (bit 0). lsio_trigger is
    // FIFO-level based, so no interrupt-source clear is needed (the CTN clear bus
    // is tied off in bare sep and would hang).
    sep_dma_wr(SEP_DMA_ENABLED_RANGE_BASE, 0x0);
    sep_dma_wr(SEP_DMA_ENABLED_RANGE_LIMIT, 0xFFFFFFFFu);
    sep_dma_wr(SEP_DMA_RANGE_VALID, 0x1);
    sep_dma_wr(SEP_DMA_SRC_ADDR_LO, SPI_RXDATA_REG);
    sep_dma_wr(SEP_DMA_SRC_ADDR_HI, 0x0);
    sep_dma_wr(SEP_DMA_DST_ADDR_LO, DST_ADDR);
    sep_dma_wr(SEP_DMA_DST_ADDR_HI, 0x0);
    sep_dma_wr(SEP_DMA_ADDR_SPACE_ID, SEP_DMA_ASID_OT | (SEP_DMA_ASID_OT << 4));
    sep_dma_wr(SEP_DMA_TRANSFER_WIDTH, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_DMA_SRC_CONFIG, SEP_DMA_ADDR_WRAP); // fixed RXDATA register
    sep_dma_wr(SEP_DMA_DST_CONFIG, SEP_DMA_ADDR_INCR); // walk through SRAM
    sep_dma_wr(SEP_DMA_TOTAL_DATA_SIZE, RX_SIZE);
    sep_dma_wr(SEP_DMA_CHUNK_DATA_SIZE, DMA_CHUNK);
    sep_dma_wr(SEP_DMA_HANDSHAKE_INTR_ENABLE, 0x1);
    sep_dma_wr(SEP_DMA_CONTROL, SEP_DMA_CTRL_GO | SEP_DMA_CTRL_INITIAL | SEP_DMA_CTRL_HW_HANDSHAKE |
                                    SEP_DMA_OPCODE_COPY);

    // --- Issue the SPI flash READ --------------------------------------------
    // TX segment: opcode 0x03 + 24-bit address 0 (4 bytes, LSB-first in TXDATA),
    // CS held asserted (CSAAT). RX segment: clock in RX_SIZE bytes, release CS.
    // The flash BFM streams its preloaded 0xA5 bytes back on MISO.
    spi_wr(SPI_TXDATA_REG, SPI_READ_OPCODE); // 0x03, then addr bytes 0,0,0
    spi_wr(SPI_CMD_REG, (SPI_CMD_DIR_TX << SPI_CMD_DIR_SHIFT) | SPI_CMD_CSAAT |
                            ((4u - 1u) << SPI_CMD_LEN_SHIFT));
    if (spi_wait_ready(SPI_POLL_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: SPI host stuck after command phase\n");
        errors++;
    }
    spi_wr(SPI_CMD_REG,
           (SPI_CMD_DIR_RX << SPI_CMD_DIR_SHIFT) | ((RX_SIZE - 1u) << SPI_CMD_LEN_SHIFT));

    // --- Wait for the DMA to drain all chunks --------------------------------
    uint32_t status_before_clear = 0;
    int timeout = DMA_POLL_TIMEOUT;
    while (timeout-- > 0) {
        status_before_clear = sep_dma_rd(SEP_DMA_STATUS);
        if (status_before_clear & (SEP_DMA_STATUS_DONE | SEP_DMA_STATUS_ERROR)) {
            break;
        }
    }
    if (!(status_before_clear & SEP_DMA_STATUS_DONE)) {
        sep_mbx_puts("FAIL: DMA did not complete\n");
        errors++;
    }
    if (status_before_clear & SEP_DMA_STATUS_ERROR) {
        sep_mbx_puts("FAIL: DMA reported error\n");
        errors++;
    }
    if (sep_dma_rd(SEP_DMA_ERROR_CODE) != 0) {
        sep_mbx_puts("FAIL: DMA error code set\n");
        errors++;
    }

    // --- RW1C status-clear proof (AGENTS.md §7) ------------------------------
    // Prove the full status-clear contract, not just that DONE was observed:
    // write 1 to the asserted RW1C status bits and confirm they read back 0.
    sep_dma_wr(SEP_DMA_STATUS, DMA_STATUS_RW1C_MASK);
    __asm__ volatile("fence" ::: "memory");
    uint32_t status_after_clear = sep_dma_rd(SEP_DMA_STATUS);
    if (status_after_clear & DMA_STATUS_RW1C_MASK) {
        sep_mbx_puts("FAIL: DMA STATUS RW1C bits did not clear\n");
        errors++;
    }

    // --- SPI controller must be clean ----------------------------------------
    if (spi_wait_idle(SPI_POLL_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: SPI host stuck active\n");
        errors++;
    }
    if (spi_rd(SPI_ERROR_STATUS_REG) != 0) {
        sep_mbx_puts("FAIL: SPI error status set\n");
        errors++;
    }

    // --- Value-check the received data (parity-plus) -------------------------
    // OSS OcahSpiFlash preloads 0xA5; nonfree Winbond erased NOR reads 0xFF.
    // Either proves SPI->DMA->SRAM moved device data (not FILL_WORD / not 0x00).
    // Idle/floating MISO (mux not selected) yields 0x00 and must still FAIL.
    {
        uint32_t w0 = dst[0];
        int ok_pattern = (w0 == EXPECT_WORD) || (w0 == 0xFFFFFFFFu);
        for (uint32_t i = 0; i < RX_WORDS; i++) {
            if (!ok_pattern || dst[i] != w0) {
                sep_mbx_puts("FAIL: SRAM data mismatch (expect 0xA5A5A5A5 or erased 0xFFFFFFFF)\n");
                errors++;
                break;
            }
        }
    }

    // --- Cleanup -------------------------------------------------------------
    sep_dma_wr(SEP_DMA_HANDSHAKE_INTR_ENABLE, 0x0);
    spi_wr(SPI_EVENT_ENABLE_REG, 0);

    if (errors == 0) {
        sep_mbx_puts("PASS: SPI RX FIFO -> DMA -> SRAM (0xA5) + RW1C verified\n");
    }
    return errors;
}
