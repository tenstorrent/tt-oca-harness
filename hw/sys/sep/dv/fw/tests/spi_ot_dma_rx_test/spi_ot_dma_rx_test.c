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
// cocotb stages the reads in g_spi2_params (located by SPI2_PARAM_MAGIC): one
// read per lane width (standard 0x03, a dual read, a quad read) in a seeded
// order, each at its own flash address, with the seeded words the testbench
// preloads into the flash there. Every DMA-written SRAM word is compared with
// those words, which proves the data path at each width and not only
// completion. The test also checks that DMA DONE still reads set after the poll
// and clears only on the write-one-to-clear.
//
// main() returns the error count; crt0.s turns it into the pass/fail mailbox
// word that the boot scoreboard gates on.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"
#include "sep_spi.h"

#define RX_SIZE 64u // bytes to receive per read (multiple of 4)
#define RX_WORDS (RX_SIZE / 4u)
#define DMA_CHUNK 16u   // one chunk drains the FIFO below the watermark
#define RX_WATERMARK 4u // RX FIFO words that raise the DMA trigger
#define DST_STAGING_OFF 0x6000u
#define DST_ADDR ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR + DST_STAGING_OFF)
#define FILL_WORD 0xDEADBEEFu // pre-DMA SRAM marker
#define DMA_STATUS_RW1C_MASK \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)

#define DMA_POLL_TIMEOUT 200000
#define SPI_POLL_TIMEOUT 200000

// Sentinel the cocotb test searches for in the DTCM image to locate the block.
#define SPI2_PARAM_MAGIC 0x5A11D0A5u
#define MAX_READS 3
#define READ_STRIDE (2u + RX_WORDS)

// Read block. [0]=magic, [1]=read count (1..MAX_READS), then per read
// [opcode, flash addr, RX_WORDS words the flash holds there]. Word i holds the
// flash bytes at addr + 4i, the first byte in bits 7:0 (ByteOrder 1). Volatile
// so the patched values are not folded. The directed default stages no read:
// the words must match the flash preload, which only the cocotb test makes.
volatile uint32_t g_spi2_params[2 + MAX_READS * READ_STRIDE] = {
    SPI2_PARAM_MAGIC,
    0u,
};

// Arms the Secure DMA: RXDATA (fixed/WRAP) -> SRAM (incrementing), hardware
// handshake from the SPI DMA trigger. The trigger follows the FIFO level, so no
// interrupt-source clear is needed (the CTN clear bus is tied off in bare sep
// and would hang).
static void dma_arm_rx(void) {
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, SECURE_DMA__RANGE_VALID__RANGE_VALID_bm);
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
}

// One staged read: SPI read at the opcode's lane width -> DMA -> SRAM, then the
// DMA status, the SPI host state, and every SRAM word against the block.
static int run_read(uint32_t idx, uint32_t opcode, uint32_t addr, volatile uint32_t *want) {
    int errors = 0;
    uint32_t lanes = sep_spi_flash_data_lanes(opcode);
    sep_mbx_puts("READ idx=");
    sep_mbx_puthex(idx);
    sep_mbx_puts(" op=");
    sep_mbx_puthex(opcode);
    sep_mbx_puts(" addr=");
    sep_mbx_puthex(addr);
    sep_mbx_putc('\n');
    if (lanes == 0u || opcode == SEP_SPI_OP_PP || opcode == SEP_SPI_OP_QPP) {
        sep_mbx_puts("FAIL: staged opcode is not a flash read\n");
        return 1;
    }

    // A staged pattern with one byte value cannot tell a stuck lane from data.
    uint32_t b0 = want[0] & 0xFFu;
    int uniform = 1;
    for (uint32_t i = 0; i < RX_WORDS && uniform; i++) {
        for (uint32_t k = 0; k < 4u; k++) {
            if (((want[i] >> (8u * k)) & 0xFFu) != b0) uniform = 0;
        }
    }
    if (uniform) {
        sep_mbx_puts("FAIL: staged read pattern holds one byte value\n");
        return 1;
    }

    // --- Clear the SRAM destination ------------------------------------------
    volatile uint32_t *dst = (volatile uint32_t *)DST_ADDR;
    for (uint32_t i = 0; i < RX_WORDS; i++) {
        dst[i] = FILL_WORD;
    }
    dma_arm_rx();

    // --- Issue the SPI flash read --------------------------------------------
    // The segments follow the opcode (sep_spi_flash_read_issue); the RX segment
    // clocks in RX_SIZE bytes at the opcode's data width and releases CS.
    if (sep_spi_flash_read_issue(opcode, addr, RX_SIZE) != 0) {
        sep_mbx_puts("FAIL: SPI host stuck while the read was issued\n");
        errors++;
    }

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
    // DONE is write-one-to-clear and a read has no side effect, so a second read
    // after the poll must still show it set. That rules out a bit that clears on
    // read or drops by itself, so the clear seen after the write is the write's.
    uint32_t status_pre_w1c = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    if (!(status_pre_w1c & SECURE_DMA__STATUS__DONE_bm)) {
        sep_mbx_puts("FAIL: CHK-RW1C DMA DONE not sticky before W1C status=");
        sep_mbx_puthex(status_pre_w1c);
        sep_mbx_putc('\n');
        errors++;
    }
    // Write one to the status bits and check that they read back clear.
    sep_dma_wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, DMA_STATUS_RW1C_MASK);
    __asm__ volatile("fence" ::: "memory");
    uint32_t status_after_clear = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
    if (status_after_clear & DMA_STATUS_RW1C_MASK) {
        sep_mbx_puts("FAIL: CHK-RW1C DMA STATUS RW1C bits did not clear status=");
        sep_mbx_puthex(status_after_clear);
        sep_mbx_putc('\n');
        errors++;
    }
    sep_mbx_puts("CHK-RW1C: dma_status_pre_w1c=");
    sep_mbx_puthex(status_pre_w1c);
    sep_mbx_puts(" dma_status_after_w1c=");
    sep_mbx_puthex(status_after_clear);
    sep_mbx_putc('\n');

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
    // Each SRAM word must equal the staged word. The pattern holds at least two
    // byte values, so a stuck lane, the idle all-ones line, the FILL_WORD marker
    // and a partial transfer all fail.
    int data_err = 0;
    for (uint32_t i = 0; i < RX_WORDS; i++) {
        uint32_t got = dst[i];
        if (got != want[i]) {
            sep_mbx_puts("FAIL: CHK-DATAPATH op=");
            sep_mbx_puthex(opcode);
            sep_mbx_puts(" word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(got);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(want[i]);
            sep_mbx_putc('\n');
            data_err++;
        }
    }
    if (data_err == 0) {
        sep_mbx_puts("CHK-DATAPATH PASS: op=");
        sep_mbx_puthex(opcode);
        sep_mbx_puts(" width=x");
        sep_mbx_putc((char)('0' + lanes));
        sep_mbx_puts(" words=");
        sep_mbx_puthex(RX_WORDS);
        sep_mbx_puts(" bytes=");
        sep_mbx_puthex(RX_SIZE);
        sep_mbx_putc('\n');
    }
    return errors + data_err;
}

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

    if (g_spi2_params[0] != SPI2_PARAM_MAGIC) {
        sep_mbx_puts("FAIL: bad param magic\n");
        return 1;
    }
    uint32_t nreads = g_spi2_params[1];
    if (nreads < 1 || nreads > MAX_READS) {
        sep_mbx_puts("FAIL: read count outside 1..MAX_READS (the cocotb test stages the "
                     "reads)\n");
        return 1;
    }

    // --- OpenTitan SPI host init ---------------------------------------------
    sep_spi_host_init(RX_WATERMARK << SPI_CONTROLLER__CONTROL__RX_WATERMARK_bp);
    spi_wr(SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, SPI_CONTROLLER__EVENT_ENABLE__RXWM_bm);
    sep_mbx_puts("STEP SPI host configured: RX watermark, clock divider, enable\n");
    if (spi_wait_ready(SPI_POLL_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: SPI host not ready\n");
        return 1;
    }

    for (uint32_t r = 0; r < nreads; r++) {
        uint32_t base = 2u + r * READ_STRIDE;
        errors +=
            run_read(r, g_spi2_params[base], g_spi2_params[base + 1u], &g_spi2_params[base + 2u]);
    }

    // --- Cleanup -------------------------------------------------------------
    sep_dma_wr(SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x0);
    spi_wr(SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, 0);

    if (errors == 0) {
        sep_mbx_puts("PASS: SPI RX FIFO -> DMA -> SRAM (seeded pattern at each staged width) + "
                     "RW1C verified\n");
    }
    return errors;
}
