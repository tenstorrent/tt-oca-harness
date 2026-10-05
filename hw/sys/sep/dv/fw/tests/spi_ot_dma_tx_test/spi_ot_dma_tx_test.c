// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan SPI host DMA-TX test (the TX complement of spi_ot_dma_rx_test).
// The Secure DMA, in hardware-handshake mode and paced by the SPI host's TX
// watermark trigger, streams a flash page program from SRAM into the TX FIFO a
// chunk at a time. Firmware then reads the flash back over SPI and checks it
// equals the programmed data. RX stays quiescent so the shared trigger is driven
// by the TX watermark alone.
//
// cocotb owns the scenario table (g_spi3_params, located by SPI3_PARAM_MAGIC):
// one boot walks the required transfer lengths, while the seed selects legal
// flash addresses and data.
//
// After the sweep, one TX FIFO write past full, which the paced DMA never
// reaches, must latch only the overflow error; software reset plus an error
// clear must then release the host for a real flash transfer.
//
// main returns the error count; crt0.s reports PASS/FAIL. Each checker logs a
// PASS line.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_dma.h"
#include "sep_spi.h"

#define TIMEOUT 200000
#define DMA_POLL_LIM 200000
#define MAX_WORDS 16
#define MAX_CASES 3
#define PARAM_STRIDE (2 + MAX_WORDS)
#define TX_WATERMARK 4 // words; the watermark fires while the TX FIFO holds fewer
#define DMA_CHUNK 16   // bytes (= TX_WATERMARK words) per refill

#define FLASH_CMD_WREN 0x06u
#define FLASH_CMD_PP 0x02u
#define FLASH_CMD_READ 0x03u
#define FLASH_CMD_RDSR 0x05u
#define FLASH_SR_WIP (1u << 0)

// SRAM staging for the DMA source: the page program header, then the data words.
#define SRC_STAGING_OFF 0x5000u
#define SRC_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR + SRC_STAGING_OFF)

#define SPI3_PARAM_MAGIC 0x5A11D00Eu // lets cocotb locate the scenario block

// Scenario block. [0]=magic, [1]=case count, then each case is:
// [addr, nword count, data[0..MAX_WORDS-1]]. Volatile so cocotb-patched
// values are not folded. Defaults walk the same directed length cells.
volatile uint32_t g_spi3_params[2 + MAX_CASES * PARAM_STRIDE] = {
    SPI3_PARAM_MAGIC,
    3u,
    0x001000u,
    7u,
    0xC0DE0001u,
    0xC0DE0002u,
    0xC0DE0003u,
    0xC0DE0004u,
    0xC0DE0005u,
    0xC0DE0006u,
    0xC0DE0007u,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0x002000u,
    11u,
    0xD0DE0001u,
    0xD0DE0002u,
    0xD0DE0003u,
    0xD0DE0004u,
    0xD0DE0005u,
    0xD0DE0006u,
    0xD0DE0007u,
    0xD0DE0008u,
    0xD0DE0009u,
    0xD0DE000Au,
    0xD0DE000Bu,
    0,
    0,
    0,
    0,
    0,
    0x003000u,
    15u,
    0xE0DE0001u,
    0xE0DE0002u,
    0xE0DE0003u,
    0xE0DE0004u,
    0xE0DE0005u,
    0xE0DE0006u,
    0xE0DE0007u,
    0xE0DE0008u,
    0xE0DE0009u,
    0xE0DE000Au,
    0xE0DE000Bu,
    0xE0DE000Cu,
    0xE0DE000Du,
    0xE0DE000Eu,
    0xE0DE000Fu,
    0,
};

static uint32_t pack_hdr(uint32_t opcode, uint32_t addr) {
    return (opcode & 0xFF) | (((addr >> 16) & 0xFF) << 8) | (((addr >> 8) & 0xFF) << 16) |
           (((addr >> 0) & 0xFF) << 24);
}

// The command length field encodes the byte count minus one.
static uint32_t cmd_word(uint32_t direction, uint32_t len_bytes, int csaat) {
    uint32_t v =
        ((direction << SPI_CONTROLLER__COMMAND__DIRECTION_bp) &
         SPI_CONTROLLER__COMMAND__DIRECTION_bm) |
        (((len_bytes - 1) << SPI_CONTROLLER__COMMAND__LEN_bp) & SPI_CONTROLLER__COMMAND__LEN_bm);
    if (csaat) v |= SPI_CONTROLLER__COMMAND__CSAAT_bm;
    return v;
}

static void spi_init(void) {
    // RX stays quiescent; the TX watermark drives the DMA refill trigger.
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           (TX_WATERMARK << SPI_CONTROLLER__CONTROL__TX_WATERMARK_bp) |
               (1u << SPI_CONTROLLER__CONTROL__RX_WATERMARK_bp) |
               SPI_CONTROLLER__CONTROL__SPIEN_bm | SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    spi_wr(SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR, SPI_CONTROLLER__EVENT_ENABLE__TXWM_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int flash_wren(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_WREN);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

/* Returns the flash status byte, or 0xFF on timeout or an empty RX FIFO. */
static uint8_t flash_read_status(void) {
    if (spi_wait_ready(TIMEOUT)) return 0xFFu;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_RDSR);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1)); // hold CS
    if (spi_wait_ready(TIMEOUT)) return 0xFFu;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, 1, 0));
    if (spi_wait_idle(TIMEOUT)) return 0xFFu;
    if (((spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) & SPI_CONTROLLER__STATUS__RXQD_bm) >>
         SPI_CONTROLLER__STATUS__RXQD_bp) < 1u)
        return 0xFFu;
    return (uint8_t)(spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)) & 0xFFu);
}

/* Waits for the flash to finish a page program; fails on 0xFF or timeout. */
static int flash_wait_wip_clear(void) {
    for (int i = 0; i < TIMEOUT; i++) {
        uint8_t sr = flash_read_status();
        if (sr == 0xFFu) {
            sep_mbx_puts("FAIL: RDSR 0xFF while polling WIP (no flash model)\n");
            return -1;
        }
        if (!(sr & FLASH_SR_WIP)) {
            return 0;
        }
    }
    sep_mbx_puts("FAIL: timeout waiting for WIP=0 after PAGE PROGRAM\n");
    return -1;
}

// CHK-TRIGGER: the TX watermark status, which sources the DMA trigger, tracks
// the TX FIFO depth across the watermark. The trigger enables are checked for
// storage only.
static int chk_trigger(void) {
    int err = 0;

    // The SPI-side trigger enable reads back as programmed.
    uint32_t evt = spi_rd(SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!(evt & SPI_CONTROLLER__EVENT_ENABLE__TXWM_bm)) {
        sep_mbx_puts("FAIL: CHK-TRIGGER EVENT_ENABLE.TXWM not set\n");
        err++;
    }
    // The DMA handshake-interrupt enable clears interrupts and does not gate the
    // handshake; a stored 1 proves it is not stuck at zero.
    sep_dma_wr(SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    if (sep_dma_rd(SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR) != 0x1) {
        sep_mbx_puts("FAIL: CHK-TRIGGER HANDSHAKE_INTR_ENABLE did not retain 0x1\n");
        err++;
    }

    // The watermark status is set while the FIFO is empty, clears once it fills
    // past the watermark, and sets again after a software-reset drain.
    uint32_t st = spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    uint32_t txqd_empty = st & SPI_CONTROLLER__STATUS__TXQD_bm;
    int txwm_empty = !!(st & SPI_CONTROLLER__STATUS__TXWM_bm);

    for (uint32_t i = 0; i < TX_WATERMARK + 4u; i++) {
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xD0000000u + i);
    }
    st = spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    uint32_t txqd_full = st & SPI_CONTROLLER__STATUS__TXQD_bm;
    int txwm_full = !!(st & SPI_CONTROLLER__STATUS__TXWM_bm);

    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           spi_rd(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR) |
               SPI_CONTROLLER__CONTROL__SW_RST_bm); // drain FIFO
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           spi_rd(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR) & ~SPI_CONTROLLER__CONTROL__SW_RST_bm);
    st = spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    uint32_t txqd_drain = st & SPI_CONTROLLER__STATUS__TXQD_bm;
    int txwm_drain = !!(st & SPI_CONTROLLER__STATUS__TXWM_bm);

    sep_mbx_puts("CHK-TRIGGER TXQD empty=");
    sep_mbx_puthex(txqd_empty);
    sep_mbx_puts(" full=");
    sep_mbx_puthex(txqd_full);
    sep_mbx_puts(" drain=");
    sep_mbx_puthex(txqd_drain);
    sep_mbx_puts(" TXWM=");
    sep_mbx_puthex((uint32_t)((txwm_empty << 2) | (txwm_full << 1) | txwm_drain));
    sep_mbx_putc('\n');

    if (!(txqd_full > txqd_empty)) {
        sep_mbx_puts("FAIL: CHK-TRIGGER TXQD did not rise on fill\n");
        err++;
    }
    if (!(txwm_empty && !txwm_full && txwm_drain)) {
        sep_mbx_puts("FAIL: CHK-TRIGGER TXWM did not track TXQD vs watermark\n");
        err++;
    }
    if (err == 0) {
        sep_mbx_puts("CHK-TRIGGER PASS: TXWM(=lsio_trigger src) tracks TXQD across "
                     "wm (live); EVENT_ENABLE.TXWM programmed\n");
    }
    return err;
}

// Read nwords back from flash with a standard read.
static int flash_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_READ, addr));
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 1)); // command + address, hold CS
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0)); // RX, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++)
        out[i] = spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    return 0;
}

// Arm the Secure DMA in hardware-handshake mode: the source walks SRAM, the
// destination stays on the SPI TX FIFO, and each watermark trigger moves a chunk.
static void dma_arm_tx(uint32_t src, uint32_t total_bytes) {
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, SECURE_DMA__RANGE_VALID__RANGE_VALID_bm);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR,
               SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0));
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
               SEP_DMA_ASID_PAIR(SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset,
                                 SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset));
    sep_dma_wr(SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    sep_dma_wr(SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR,
               SECURE_DMA__SRC_CONFIG__INCREMENT_bm); // walk SRAM
    sep_dma_wr(SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR,
               SECURE_DMA__DST_CONFIG__WRAP_bm); // fixed TXDATA register
    sep_dma_wr(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total_bytes);
    sep_dma_wr(SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, DMA_CHUNK);
    sep_dma_wr(SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    sep_dma_wr(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
               SECURE_DMA__CONTROL__GO_bm | SECURE_DMA__CONTROL__INITIAL_TRANSFER_bm |
                   SECURE_DMA__CONTROL__HARDWARE_HANDSHAKE_ENABLE_bm | SEP_DMA_OPCODE_COPY);
}

static int run_case(uint32_t case_idx, uint32_t addr, volatile uint32_t *data, uint32_t nwords) {
    int errors = 0;
    uint32_t rd[MAX_WORDS];

    if (nwords < 1 || nwords > MAX_WORDS) {
        sep_mbx_puts("FAIL: bad nwords\n");
        return 1;
    }
    sep_mbx_puts("SCENARIO case=");
    sep_mbx_puthex(case_idx);
    sep_mbx_puts(" addr=");
    sep_mbx_puthex(addr);
    sep_mbx_puts(" nwords=");
    sep_mbx_puthex(nwords);
    sep_mbx_putc('\n');

    // Stage the DMA source in SRAM: the page program header, then the data words.
    volatile uint32_t *src = (volatile uint32_t *)SRC_BASE;
    src[0] = pack_hdr(FLASH_CMD_PP, addr);
    for (uint32_t i = 0; i < nwords; i++) src[1 + i] = data[i];
    __asm__ volatile("fence" ::: "memory");
    uint32_t total_bytes = (1u + nwords) * 4u; // header word + data words

    // More than one chunk means the watermark-triggered refill must repeat.
    sep_mbx_puts("DMA-TX case=");
    sep_mbx_puthex(case_idx);
    sep_mbx_puts(" chunks=");
    sep_mbx_puthex((total_bytes + DMA_CHUNK - 1) / DMA_CHUNK);
    sep_mbx_putc('\n');

    spi_init();

    // Write enable directly, then send the page program through the DMA.
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN timeout\n");
        return 1;
    }
    if (spi_wait_ready(TIMEOUT)) {
        sep_mbx_puts("FAIL: SPI not ready\n");
        return 1;
    }

    // Issue the TX command before starting the DMA: the host stalls for TX data
    // and the DMA feeds it on each watermark trigger.
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, total_bytes, 0));
    dma_arm_tx(SRC_BASE, total_bytes);

    // --- CHK-DMA-DONE: the handshake transfer completes without error ---
    // Done must still read set on a second read after the poll, so a read does
    // not clear it and it does not drop by itself, and must then clear on
    // write-one. Chunk-done is raised only for multi-chunk memory-to-memory
    // transfers, so it is not checked here; dma_basic_test covers it.
    uint32_t st = 0;
    int t = DMA_POLL_LIM;
    while (t-- > 0) {
        st = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) break;
    }
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) ||
        sep_dma_rd(SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR) != 0) {
        sep_mbx_puts("FAIL: CHK-DMA-DONE status=");
        sep_mbx_puthex(st);
        sep_mbx_putc('\n');
        errors++;
    } else {
        uint32_t pre = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (!(pre & SECURE_DMA__STATUS__DONE_bm)) {
            sep_mbx_puts("FAIL: CHK-DMA-DONE DMA DONE not sticky before W1C pre=");
            sep_mbx_puthex(pre);
            sep_mbx_putc('\n');
            errors++;
        } else {
            sep_dma_wr(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR,
                       SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm);
            __asm__ volatile("fence" ::: "memory");
            uint32_t post = sep_dma_rd(SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
            if (post & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)) {
                sep_mbx_puts("FAIL: CHK-DMA-DONE DMA STATUS RW1C did not read back clear post=");
                sep_mbx_puthex(post);
                sep_mbx_putc('\n');
                errors++;
            } else {
                sep_mbx_puts("CHK-DMA-DONE PASS: done held after the poll, RW1C reads back "
                             "clear pre=");
                sep_mbx_puthex(pre);
                sep_mbx_puts(" post=");
                sep_mbx_puthex(post);
                sep_mbx_puts(" (handshake mode: chunk_done is not a handshake status)\n");
            }
        }
    }

    // --- CHK-SPI-IDLE: SPI drains and reports no error ---
    if (spi_wait_idle(TIMEOUT)) {
        sep_mbx_puts("FAIL: SPI not idle\n");
        errors++;
    }
    uint32_t serr = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (serr != 0) {
        sep_mbx_puts("FAIL: CHK-SPI-IDLE ERROR_STATUS=");
        sep_mbx_puthex(serr);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-SPI-IDLE PASS: OT SPI idle + ERROR_STATUS==0\n");
    }

    // --- Precondition, not a checker: the flash finishes the program ---
    // The flash model is always ready, so this wait fails only when the flash
    // does not respond.
    if (flash_wait_wip_clear()) {
        errors++;
        return errors;
    }

    // --- CHK-DMA-TX: read the flash back -> it equals the DMA-fed data ---
    if (flash_read(addr, rd, nwords)) {
        sep_mbx_puts("FAIL: flash READ timeout\n");
        return errors + 1;
    }
    int data_ok = 1, any_nonerased = 0;
    for (uint32_t i = 0; i < nwords; i++) {
        // A flash that was never programmed reads erased, so an erased readback
        // must fail even where the compare alone would pass.
        if (rd[i] != 0xFFFFFFFFu) any_nonerased = 1;
        if (rd[i] != data[i]) {
            sep_mbx_puts("FAIL: CHK-DMA-TX word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(rd[i]);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(data[i]);
            sep_mbx_putc('\n');
            errors++;
            data_ok = 0;
        }
    }
    if (data_ok) {
        sep_mbx_puts("CHK-DMA-TX PASS: flash content == SRAM source "
                     "(SRAM->DMA->TXFIFO->flash)\n");
    }
    // --- CHK-NONVAC: the flash returned real content, not erased 0xFF ---
    if (data_ok && any_nonerased) {
        sep_mbx_puts("CHK-NONVAC PASS: programmed data differs from erased 0xFF\n");
    } else if (!any_nonerased) {
        sep_mbx_puts("FAIL: CHK-NONVAC flash readback was all-0xFF; the page "
                     "reads erased, so the content compare is vacuous\n");
        errors++;
    }

    return errors;
}

// CHK-ERR-OVERFLOW: one TX FIFO write past full must latch only the overflow
// error. The watermark-paced DMA never reaches this edge, so nothing else in the
// test proves the flow control exists. A latched error holds the host until
// software clears it, so this check runs last and ends with a software reset,
// an error clear and a real flash transfer.
#define TXFULL_WRITE_LIM 256

static int chk_err_overflow(void) {
    int err = 0;

    // No command is outstanding, so nothing drains the FIFO: fill it until the
    // host reports full.
    uint32_t writes = 0;
    while (writes < TXFULL_WRITE_LIM &&
           !(spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) & SPI_CONTROLLER__STATUS__TXFULL_bm)) {
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xE0000000u + writes);
        writes++;
    }
    if (writes >= TXFULL_WRITE_LIM) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW STATUS.TXFULL never asserted after ");
        sep_mbx_puthex(writes);
        sep_mbx_puts(" TXDATA writes\n");
        return err + 1;
    }
    sep_mbx_puts("CHK-ERR-OVERFLOW TXFULL after writes=");
    sep_mbx_puthex(writes);
    sep_mbx_putc('\n');

    // The error status is clean here (CHK-SPI-IDLE checked it per case), so the
    // one write past full is the only thing that can set a bit.
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xE0FFFFFFu);
    uint32_t es = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (es != SPI_CONTROLLER__ERROR_STATUS__OVERFLOW_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW ERROR_STATUS=");
        sep_mbx_puthex(es);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(SPI_CONTROLLER__ERROR_STATUS__OVERFLOW_bm);
        sep_mbx_putc('\n');
        err++;
    }

    // Recovery: the host must not leave software reset until both FIFOs report
    // empty; then clear the error latch.
    const uint32_t empty = SPI_CONTROLLER__STATUS__TXEMPTY_bm | SPI_CONTROLLER__STATUS__RXEMPTY_bm;
    uint32_t ctrl = spi_rd(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl | SPI_CONTROLLER__CONTROL__SW_RST_bm);
    uint32_t rst_st = 0;
    int rst_t = TIMEOUT;
    while (rst_t-- > 0) {
        rst_st = spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if ((rst_st & empty) == empty) break;
    }
    if ((rst_st & empty) != empty) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW SW_RST held but STATUS.TXEMPTY/RXEMPTY "
                     "never both set, STATUS=");
        sep_mbx_puthex(rst_st);
        sep_mbx_putc('\n');
        err++;
    }
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl & ~SPI_CONTROLLER__CONTROL__SW_RST_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
    uint32_t residual = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (residual != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW ERROR_STATUS did not W1C-clear, residual=");
        sep_mbx_puthex(residual);
        sep_mbx_putc('\n');
        err++;
    }

    // A released host completes a real status read; a host still held returns
    // nothing and the helper reports 0xFF.
    uint8_t sr = flash_read_status();
    if (sr == 0xFFu) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW RDSR returned 0xFF after recovery; the "
                     "host did not resume\n");
        err++;
    }
    if (err == 0) {
        sep_mbx_puts("CHK-ERR-OVERFLOW PASS: a TXDATA write past STATUS.TXFULL latched "
                     "only ERROR_STATUS.OVERFLOW, W1C released it, and the host ran a "
                     "flash RDSR again\n");
    }
    return err;
}

int main(void) {
    int errors = 0;

    /* Staging offset must stay inside the generated SEP SRAM aperture. */
    if (SRC_STAGING_OFF + ((1u + MAX_WORDS) * 4u) > (uint32_t)SEP_TOP_SEP_SRAM_SIZE) {
        sep_mbx_puts("FAIL: SRC staging offset outside SEP SRAM\n");
        return 1;
    }

    sep_outbound_filter_init();
    sep_mbx_puts("SEP SPI OT DMA TX test\n");

    if (g_spi3_params[0] != SPI3_PARAM_MAGIC) {
        sep_mbx_puts("FAIL: bad param magic\n");
        return 1;
    }
    uint32_t ncases = g_spi3_params[1];
    if (ncases < 1 || ncases > MAX_CASES) {
        sep_mbx_puts("FAIL: bad case count\n");
        return 1;
    }
    sep_mbx_puts("RAND-REP cases=");
    sep_mbx_puthex(ncases);
    sep_mbx_putc('\n');

    spi_init();
    // Check the trigger source once before the transfer sweep relies on it.
    errors += chk_trigger();

    for (uint32_t c = 0; c < ncases; c++) {
        uint32_t base = 2u + c * PARAM_STRIDE;
        uint32_t addr = g_spi3_params[base];
        uint32_t nwords = g_spi3_params[base + 1u];
        volatile uint32_t *data = &g_spi3_params[base + 2u];
        errors += run_case(c, addr, data, nwords);
    }

    // Last: the TX-FIFO flow-control error edge the paced DMA never reaches.
    errors += chk_err_overflow();

    if (errors == 0) {
        sep_mbx_puts("CHK-RAND-REP PASS: walked deterministic DMA length/trigger cells\n");
        sep_mbx_puts("PASS: OT SPI DMA-TX program/readback all OK\n");
    }
    return errors;
}
