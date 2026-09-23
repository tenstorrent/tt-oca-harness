// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan-SPI DMA-TX firmware test. The complement of sep_spi_ot_dma_rx
// (SPI RX FIFO -> DMA -> SRAM): here SRAM -> Secure DMA
// (hardware handshake) -> OT SPI host TX FIFO -> flash. The OT SPI TX watermark
// drives lsio_trigger, which refills the TX FIFO from SRAM a chunk at a time:
//
//   spi_host.lsio_trigger_o(=tx_wm|rx_wm) -> sep.lsio_trigger[0] -> secure_dma
//
// STRONGER than the reference spi_ot_dma_tx_test (which DMA-streams raw bytes and only
// checks "DMA done + no SPI error"): here the DMA feeds a REAL flash PAGE PROGRAM
// stream (opcode 0x02 + 24-bit addr + data) from SRAM, and the firmware then reads
// the flash back over SPI and value-checks it == the programmed data. RX is kept
// quiescent so the single lsio_trigger (tx_wm | rx_wm) is TX-watermark-driven.
//
// RANDOMIZATION ([RAND-REP]): cocotb owns the scenario table in g_spi3_params
// (patched at SPI3_PARAM_MAGIC). One boot deterministically walks the required
// length/trigger cells, while the seed selects legal flash addresses and data.
//
// After the sweep, CHK-ERR-OVERFLOW provokes the one TX-FIFO flow-control edge
// the watermark-paced DMA is designed never to hit: a TXDATA write past
// STATUS.TXFULL. The host latches ERROR_STATUS.OVERFLOW and holds its core off
// until software clears it, so the checker also proves the CTRL.SW_RST + W1C
// recovery with a real flash RDSR afterwards.
//
// main returns the error count; crt0.s emits PASS/FAIL magic. Each checker logs
// a positive PASS line.

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
#define TX_WATERMARK 4 // words; tx_wm asserts when TXQD < this
#define DMA_CHUNK 16   // bytes (= TX_WATERMARK words) per refill

#define FLASH_CMD_WREN 0x06u
#define FLASH_CMD_PP 0x02u
#define FLASH_CMD_READ 0x03u
#define FLASH_CMD_RDSR 0x05u
#define FLASH_SR_WIP (1u << 0)

// SRAM staging for the DMA source: word0 = PP cmd+addr header, then data words.
#define SRC_STAGING_OFF 0x5000u
#define SRC_BASE ((uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + SRC_STAGING_OFF)

#define SPI3_PARAM_MAGIC 0x5A11D00Eu // little-endian in mem: 0E D0 11 5A

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

// LEN encodes byte count - 1. Every field goes through the generated position
// and mask: the register layout is owned by the OpenTitan spi_host block, and
// hand-packed bit positions silently break when it changes.
static uint32_t cmd_word(uint32_t direction, uint32_t len_bytes, int csaat) {
    uint32_t v =
        ((direction << SPI_CONTROLLER__COMMAND__DIRECTION_bp) &
         SPI_CONTROLLER__COMMAND__DIRECTION_bm) |
        (((len_bytes - 1) << SPI_CONTROLLER__COMMAND__LEN_bp) & SPI_CONTROLLER__COMMAND__LEN_bm);
    if (csaat) v |= SPI_CONTROLLER__COMMAND__CSAAT_bm;
    return v;
}

static void spi_init(void) {
    // RX_WM=1 (RX kept quiescent), TX_WM drives the refill trigger.
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           (TX_WATERMARK << SPI_CONTROLLER__CONTROL__TX_WATERMARK_bp) |
               (1u << SPI_CONTROLLER__CONTROL__RX_WATERMARK_bp) |
               SPI_CONTROLLER__CONTROL__SPIEN_bm | SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR,
           SPI_CONTROLLER__EVENT_ENABLE__TXWM_bm); // TX watermark -> lsio_trigger
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int flash_wren(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_WREN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

/* RDSR (0x05). Returns status byte, or 0xFF on timeout / empty RX. */
static uint8_t flash_read_status(void) {
    if (spi_wait_ready(TIMEOUT)) return 0xFFu;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_RDSR);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1)); // CSAAT
    if (spi_wait_ready(TIMEOUT)) return 0xFFu;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, 1, 0));
    if (spi_wait_idle(TIMEOUT)) return 0xFFu;
    if (((spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) >> SPI_CONTROLLER__STATUS__RXQD_bp) &
         0xFFu) < 1u)
        return 0xFFu;
    return (uint8_t)(spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)) & 0xFFu);
}

/* Poll flash WIP=0 after PAGE PROGRAM (fail-closed on 0xFF / timeout). */
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

// CHK-TRIGGER: positively prove the TX-watermark signal that SOURCES
// lsio_trigger (= tx_wm | rx_wm) correlates with TXQD crossing TX_WATERMARK.
// EVENT_ENABLE.TXWM is programmed (CSR storage). HANDSHAKE_INTR_ENABLE is the
// interrupt-clear bitmap for CTN, not the DMA handshake gate; dma_arm_tx writes
// it. The live evidence is STATUS.TXWM tracking TXQD.
static int chk_trigger(void) {
    int err = 0;

    // SPI-side trigger source enable: EVENT_ENABLE.TXWM reads back as programmed.
    uint32_t evt = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR);
    if (!(evt & SPI_CONTROLLER__EVENT_ENABLE__TXWM_bm)) {
        sep_mbx_puts("FAIL: CHK-TRIGGER EVENT_ENABLE.TXWM not set\n");
        err++;
    }
    // DMA HANDSHAKE_INTR_ENABLE is the CTN interrupt-clear bitmap (unused here);
    // require it still stores a programmed 1 so a stuck-at-zero decode fails.
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    if (sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR) != 0x1) {
        sep_mbx_puts("FAIL: CHK-TRIGGER HANDSHAKE_INTR_ENABLE did not retain 0x1\n");
        err++;
    }

    // TXWM tracks TXQD across the watermark: empty (TXQD=0 < wm) -> TXWM=1;
    // fill past wm -> TXWM=0; SW_RST drain -> TXWM=1.
    uint32_t st = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    uint32_t txqd_empty = st & SPI_CONTROLLER__STATUS__TXQD_bm;
    int txwm_empty = !!(st & SPI_CONTROLLER__STATUS__TXWM_bm);

    for (uint32_t i = 0; i < TX_WATERMARK + 4u; i++) {
        spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xD0000000u + i);
    }
    st = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
    uint32_t txqd_full = st & SPI_CONTROLLER__STATUS__TXQD_bm;
    int txwm_full = !!(st & SPI_CONTROLLER__STATUS__TXWM_bm);

    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR) |
               SPI_CONTROLLER__CONTROL__SW_RST_bm); // drain FIFO
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR) &
               ~SPI_CONTROLLER__CONTROL__SW_RST_bm);
    st = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
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
        // Say exactly what was proven: TXWM/TXQD correlation is the live evidence.
        sep_mbx_puts("CHK-TRIGGER PASS: TXWM(=lsio_trigger src) tracks TXQD across "
                     "wm (live); EVENT_ENABLE.TXWM programmed\n");
    }
    return err;
}

// Read nwords back from flash via a standard READ (0x03) -- firmware-side value
// check that the DMA-fed PAGE PROGRAM actually reached the flash.
static int flash_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_READ, addr));
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 1)); // cmd+addr, CSAAT
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0)); // RX, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++)
        out[i] = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    return 0;
}

// Arm the Secure DMA in hardware-handshake mode: SRC=SRAM (incrementing),
// DST=SPI TXDATA (fixed/wrap), refilled on the TX-watermark lsio_trigger.
static void dma_arm_tx(uint32_t src, uint32_t total_bytes) {
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0x0);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xFFFFFFFFu);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, src);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_SRC_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR,
               OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0));
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_DST_ADDR_HI_BASE_ADDR, 0x0);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_ADDR_SPACE_ID_BASE_ADDR,
               SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset |
                   (SECURE_DMA__ADDR_SPACE_ID__SRC_ASID_reset << 4));
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_TRANSFER_WIDTH_BASE_ADDR, SEP_DMA_WIDTH_4B);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_SRC_CONFIG_BASE_ADDR,
               SECURE_DMA__SRC_CONFIG__INCREMENT_bm); // walk SRAM
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_DST_CONFIG_BASE_ADDR,
               SECURE_DMA__SRC_CONFIG__WRAP_bm); // fixed TXDATA register
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, total_bytes);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_CHUNK_DATA_SIZE_BASE_ADDR, DMA_CHUNK);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_HANDSHAKE_INTR_ENABLE_BASE_ADDR, 0x1);
    sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR,
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

    // Build the DMA source in SRAM: [PP cmd+addr] then the data words.
    volatile uint32_t *src = (volatile uint32_t *)SRC_BASE;
    src[0] = pack_hdr(FLASH_CMD_PP, addr);
    for (uint32_t i = 0; i < nwords; i++) src[1 + i] = data[i];
    __asm__ volatile("fence" ::: "memory");
    uint32_t total_bytes = (1u + nwords) * 4u; // cmd+addr word + data words

    // The DMA TOTAL spans this many 16-byte chunks; >1 means the TX-watermark
    // refill loop must iterate (the dynamic half of CHK-TRIGGER).
    sep_mbx_puts("DMA-TX case=");
    sep_mbx_puthex(case_idx);
    sep_mbx_puts(" chunks=");
    sep_mbx_puthex((total_bytes + DMA_CHUNK - 1) / DMA_CHUNK);
    sep_mbx_putc('\n');

    spi_init();

    // WREN (direct), then the PAGE PROGRAM stream via DMA-fed TX.
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN timeout\n");
        return 1;
    }
    if (spi_wait_ready(TIMEOUT)) {
        sep_mbx_puts("FAIL: SPI not ready\n");
        return 1;
    }

    // Issue the TX command BEFORE starting the DMA (reference suite order): the SPI stalls
    // for TX data, the DMA feeds it on each TX-watermark trigger. LEN == TOTAL-1.
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, total_bytes, 0));
    dma_arm_tx(SRC_BASE, total_bytes);

    // --- CHK-DMA-DONE: run the handshake transfer to completion ---
    // STATUS.chunk_done is raised only when hardware handshake is *off*
    // (secure_dma.sv: chunk_done = !cfg_handshake_en). This path is handshake
    // mode, so the checker is DONE + clean error + RW1C. Firmware-paced
    // CHUNK_DONE is `dma_basic_test`.
    uint32_t st = 0;
    int t = DMA_POLL_LIM;
    while (t-- > 0) {
        st = sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (st & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ERROR_bm)) break;
    }
    if (!(st & SECURE_DMA__STATUS__DONE_bm) || (st & SECURE_DMA__STATUS__ERROR_bm) ||
        sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR) != 0) {
        sep_mbx_puts("FAIL: CHK-DMA-DONE status=");
        sep_mbx_puthex(st);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_dma_wr(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR,
                   SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm);
        __asm__ volatile("fence" ::: "memory");
        uint32_t post = sep_dma_rd(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR);
        if (post & (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__CHUNK_DONE_bm)) {
            sep_mbx_puts("FAIL: DMA STATUS RW1C did not read back clear post=");
            sep_mbx_puthex(post);
            sep_mbx_putc('\n');
            errors++;
        } else {
            sep_mbx_puts("CHK-DMA-DONE PASS: done RW1C reads back clear "
                         "(handshake mode: chunk_done is not a handshake status)\n");
        }
    }

    // --- CHK-SPI-IDLE: SPI drains and reports no error ---
    if (spi_wait_idle(TIMEOUT)) {
        sep_mbx_puts("FAIL: SPI not idle\n");
        errors++;
    }
    uint32_t serr = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (serr != 0) {
        sep_mbx_puts("FAIL: CHK-SPI-IDLE ERROR_STATUS=");
        sep_mbx_puthex(serr);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-SPI-IDLE PASS: OT SPI idle + ERROR_STATUS==0\n");
    }

    // --- Precondition, not a checker: settle the device before the readback ---
    // The flash BFM is instant-ready, so the first defined RDSR already reads
    // WIP=0 and a "WIP clear" assertion could not fail; the poll is fail-closed
    // on 0xFF/timeout. CHK-DMA-TX below is the data proof.
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
        // Scan what the flash returned, not what was staged. The source is
        // forced non-erased by the config, so scanning it can never fail; a
        // readback that is all-0xFF is the real vacuous case -- a flash that was
        // never programmed reads erased, and CHK-DMA-TX would then compare
        // erased against erased and pass.
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

// CHK-ERR-OVERFLOW: firmware pushing TXDATA past the TX FIFO capacity.
// spi_host.sv: error_overflow = tx_valid & ~tx_ready, i.e. a TXDATA write
// the FIFO cannot accept. Nothing else in this test can reach that edge -- the
// DMA is paced by the TX watermark precisely so it never does -- so the flow
// control the whole DMA-TX path depends on is otherwise never proven to exist.
//
// The host keeps its core disabled while any ERROR_STATUS bit is latched
// (en = en_sw & ~enb_error), so the injection is last and is followed by a
// CTRL.SW_RST flush + W1C, then a real bus transfer to prove the release.
#define TXFULL_WRITE_LIM 256

static int chk_err_overflow(void) {
    int err = 0;

    // No command is outstanding, so nothing drains the FIFO: keep writing until
    // the HOST reports TXFULL. The bound is a guard, not the contract.
    uint32_t writes = 0;
    while (writes < TXFULL_WRITE_LIM && !(spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) &
                                          SPI_CONTROLLER__STATUS__TXFULL_bm)) {
        spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xE0000000u + writes);
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

    // ERROR_STATUS is clean up to here (CHK-SPI-IDLE asserted it per case), so
    // the one write past full is the only thing that can set a bit.
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0xE0FFFFFFu);
    uint32_t es = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (es != SPI_CONTROLLER__ERROR_STATUS__OVERFLOW_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW ERROR_STATUS=");
        sep_mbx_puthex(es);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(SPI_CONTROLLER__ERROR_STATUS__OVERFLOW_bm);
        sep_mbx_putc('\n');
        err++;
    }

    // Recovery: SW_RST drains the FIFOs and the command queue, then W1C the latch.
    uint32_t ctrl = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl | SPI_CONTROLLER__CONTROL__SW_RST_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           ctrl & ~SPI_CONTROLLER__CONTROL__SW_RST_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
    uint32_t residual = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (residual != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-OVERFLOW ERROR_STATUS did not W1C-clear, residual=");
        sep_mbx_puthex(residual);
        sep_mbx_putc('\n');
        err++;
    }

    // Positive proof the host was released: a real RDSR round trip to the device.
    // A host still disabled returns nothing and the helper reports 0xFF.
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
    if (SRC_STAGING_OFF + ((1u + MAX_WORDS) * 4u) > (uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE) {
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
    // CHK-TRIGGER: prove the TX-watermark trigger source + DMA trigger-enable
    // once before the RAND-REP transfer sweep relies on them.
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
