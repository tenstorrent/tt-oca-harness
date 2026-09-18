// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan-SPI RX -> Secure-DMA -> SRAM firmware test (OSS port of the
// reference suite sep_spi_ot_dma_rx_test). The EL2 CPU configures the OpenTitan
// SPI host, arms the Secure DMA in hardware-handshake mode (SRC = SPI RXDATA,
// fixed/WRAP; DST = SRAM, incrementing), then issues a SPI read. As the SPI RX
// FIFO crosses its watermark, the controller raises lsio_trigger, which drains a
// chunk into SRAM via the DMA hardware handshake:
//
//   spi_host.lsio_trigger_o -> sep.lsio_trigger[0] -> secure_dma.lsio_trigger_i[0]
//
// This whole datapath is internal to bare `sep`
// (`hw/sys/sep/rtl/sep.sv`: `lsio_trigger[0] = sep_io_spi_req_o.lsio_trigger`).
// Exercises SPI-FIFO -> DMA on the OpenTitan SPI line.
//
// Beyond the reference suite: the reference test only checks "DMA done + no SPI error"
// because it clocks idle MISO (no flash model) and leaves the received data
// unchecked. Here the OSS flash BFM is preloaded with a known constant (0xA5),
// the firmware issues a real flash READ (0x03), and then VALUE-CHECKS that every
// DMA-written SRAM word == 0xA5A5A5A5 -- so the checker actually proves the
// SPI->DMA->SRAM data path, not just completion. It also proves the DMA STATUS
// RW1C clear contract (write-1-clear -> reads back 0).
//
// main() returns the error count; crt0.s turns 0 -> PASS magic, non-zero ->
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
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)

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
    sep_mbx_puts("STEP filter init done; flash model preloaded by the host\n");

    // --- OpenTitan SPI host init ---------------------------------------------
    // RX watermark = 4 words (asserts lsio_trigger), TX watermark = 0, enable the
    // controller + output.
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           (RX_WATERMARK << SPI_CONTROLLER__CONTROL__RX_WATERMARK_bp) |
               SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm | SPI_CONTROLLER__CONTROL__SPIEN_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    sep_mbx_puts("STEP SPI host configured: RX watermark, clock divider, enable\n");
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR,
           SPI_CONTROLLER__EVENT_ENABLE__RXWM_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR,
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
    // Hardware handshake from the SPI lsio_trigger (bit 0). lsio_trigger is
    // FIFO-level based, so no interrupt-source clear is needed (the CTN clear bus
    // is tied off in bare sep and would hang).
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);
    sep_mbx_puts("STEP DMA armed: RXDATA(WRAP) -> SRAM(INCR), hardware handshake\n");
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR,
               OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR, DST_ADDR);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
               SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset |
                   (SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset << 4));
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR,
               SECURE_DMA__SRC_CONFIG__WRAP_bm); // fixed RXDATA register
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR,
               SECURE_DMA__SRC_CONFIG__INCREMENT_bm); // walk through SRAM
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, RX_SIZE);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, DMA_CHUNK);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
               SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                   SECURE_DMA__CONTROL__HARDWARE_HANDSHAKE_ENABLE_bm | SEP_DMA_OPCODE_COPY);

    // --- Issue the SPI flash READ --------------------------------------------
    // TX segment: opcode 0x03 + 24-bit address 0 (4 bytes, LSB-first in TXDATA),
    // CS held asserted (CSAAT). RX segment: clock in RX_SIZE bytes, release CS.
    // The flash BFM streams its preloaded 0xA5 bytes back on MISO.
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0),
           SPI_READ_OPCODE); // 0x03, then addr bytes 0,0,0
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           (SPI_CMD_DIR_TX << SPI_CONTROLLER__COMMAND__DIRECTION_bp) |
               SPI_CONTROLLER__COMMAND__CSAAT_bm | ((4u - 1u) << SPI_CONTROLLER__COMMAND__LEN_bp));
    if (spi_wait_ready(SPI_POLL_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: SPI host stuck after command phase\n");
        errors++;
    }
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           (SPI_CMD_DIR_RX << SPI_CONTROLLER__COMMAND__DIRECTION_bp) |
               ((RX_SIZE - 1u) << SPI_CONTROLLER__COMMAND__LEN_bp));
    sep_mbx_puts("STEP flash READ issued: opcode 0x03 + 24-bit address\n");

    // --- Wait for the DMA to drain all chunks --------------------------------
    uint32_t status_before_clear = 0;
    int timeout = DMA_POLL_TIMEOUT;
    while (timeout-- > 0) {
        status_before_clear = sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
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
    if (sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR) != 0) {
        sep_mbx_puts("FAIL: DMA error code set\n");
        errors++;
    }

    // --- RW1C status-clear proof ---------------------------------------------
    // Prove the full status-clear contract, not just that DONE was observed:
    // write 1 to the asserted RW1C status bits and confirm they read back 0.
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, DMA_STATUS_RW1C_MASK);
    __asm__ volatile("fence" ::: "memory");
    uint32_t status_after_clear = sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
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
    uint32_t spi_err_status = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (spi_err_status != 0) {
        sep_mbx_puts("FAIL: SPI error status set\n");
        errors++;
    }

    // CHK-NOERR evidence: the four values the legs above already read, so the
    // checker is auditable from the log rather than only from a silent pass.
    sep_mbx_puts("CHK-NOERR: dma_status=");
    sep_mbx_puthex(status_after_clear);
    sep_mbx_puts(" dma_err_code=");
    sep_mbx_puthex(sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR));
    sep_mbx_puts(" spi_idle=");
    sep_mbx_putc(spi_idle ? '1' : '0');
    sep_mbx_puts(" spi_err_status=");
    sep_mbx_puthex(spi_err_status);
    sep_mbx_putc('\n');

    // --- Value-check the received data ---------------------------------------
    // The OSS OcahSpiFlash BFM preloads RX_PATTERN across the read window, so
    // EXPECT_WORD is the only acceptable result and the compare is exclusive.
    //
    // All-ones must NOT be accepted here. The TB idles spi_miso_i high, the
    // BFM's backing store is 0xFF everywhere outside the 64 preloaded bytes,
    // and an unrecognised opcode drains to CS# high without ever driving MISO.
    // So 0xFFFFFFFF is exactly the signature of a broken RX path -- mis-wired
    // MISO, a garbled address phase, a misinterpreted opcode -- and accepting
    // it would let all three of those pass while the log claimed 0xA5.
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
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x0);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    if (errors == 0) {
        sep_mbx_puts("PASS: SPI RX FIFO -> DMA -> SRAM (0xA5) + RW1C verified\n");
    }
    return errors;
}
