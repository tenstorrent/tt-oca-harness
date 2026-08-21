// SPDX-License-Identifier: Apache-2.0
//
// SEP OpenTitan-SPI flash command-breadth firmware test (OSS rep SPI flash command breadth). Direct
// cpu-firmware port of the reference spi_ot_flash_write_read_test +
// spi_ot_flash_sector_erase_test, driving the OT SPI host (@ 0x10B0_0000) against
// the OcahSpiFlash BFM. Firmware-mode (like every reference spi_ot flash test + the
// Phase-1 sep_spi_ot_dma_rx) -- the OT spi_host multi-command flash sequence runs
// from the EL2 CPU, not the no_cpu AXI splice.
//
// Flow: WREN -> PAGE PROGRAM (single TX segment: cmd+addr+data) -> READ + verify
// == pattern -> WREN -> SECTOR ERASE -> READ + verify == 0xFF. ERROR_STATUS
// checked == 0. The RDSR/WIP status-poll path is deferred: the current BFM is
// instant-ready and the split RDSR transaction sequence needs separate bring-up.
//
// The BFM memory inits to 0xFF (erased), so PAGE PROGRAM (NOR-AND) writes the
// pattern directly. CHK-DUAL-QUAD is deferred: the BFM models neither the
// 0x3B/0x6B opcodes nor multi-lane DQ (single-bit data phase).
//
// RANDOMIZATION ([RAND-REP]): the scenario (flash address, word count, data) is
// held in the g_spi1_params block below. The committed defaults are the directed
// scenario, so the firmware runs standalone; the cocotb test (single source of
// randomness, seeded by the run seed) overwrites the block in the staged DTCM
// image per run by locating the SPI1_PARAM_MAGIC sentinel. The firmware just
// consumes the block, so the same compiled image covers every seed.
//
// main returns the error count; start.S emits PASS (0xCAFEBABE) / FAIL
// (0xDEADBEEF) magic on the 0x8000_0000 mailbox. Each checker logs a positive
// PASS line.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_spi.h"

#define TIMEOUT 200000
#define WIP_POLL_LIM 100000
#define MAX_WORDS 16

#define FLASH_CMD_WREN 0x06u
#define FLASH_CMD_RDSR 0x05u
#define FLASH_CMD_PP 0x02u
#define FLASH_CMD_READ 0x03u
#define FLASH_CMD_ERASE 0x20u
#define FLASH_SR_WIP (1u << 0)
#define FLASH_SR_WEL (1u << 1)

// Non-ASCII sentinel that the cocotb test byte-searches for in the DTCM image to
// locate this block (avoids needing the .map). Stored little-endian: DE C0 11 5A.
#define SPI1_PARAM_MAGIC 0x5A11C0DEu

// Scenario block. Layout: [0]=magic, [1]=flash addr, [2]=word count (1..MAX_WORDS),
// [3 .. 3+count-1]=data words (LSB byte sent first). volatile so the compiler
// cannot fold reads of the (run-time patched) values. Committed defaults are the
// directed scenario.
volatile uint32_t g_spi1_params[3 + MAX_WORDS] = {
    SPI1_PARAM_MAGIC, 0x000000u, 4u, 0xA5C31234u, 0xDEADBEEFu, 0x0BADF00Du, 0xCAFEBABEu,
};

static uint32_t cmd_word(uint32_t direction, uint32_t len_bytes, int csaat) {
    uint32_t v = (direction << SPI_CONTROLLER__CMD__DIRECTION_bp) | ((len_bytes - 1) & 0x1FF);
    if (csaat) {
        v |= SPI_CONTROLLER__CMD__CSAAT_bm;
    }
    return v;
}

static uint32_t pack_hdr(uint32_t opcode, uint32_t addr) {
    // byte0=opcode, byte1=addr[23:16], byte2=addr[15:8], byte3=addr[7:0]
    return (opcode & 0xFF) | (((addr >> 16) & 0xFF) << 8) | (((addr >> 8) & 0xFF) << 16) |
           (((addr >> 0) & 0xFF) << 24);
}

// No SPI-mux CS release: the och_sep_spi_mux_ctrl_ot CSR is a nonfree shim absent from this
// repository (the wrapper's SPI is a struct boundary), so nothing holds CS
// deasserted and the 0x2000_0000 extension aperture decode-errors.

static void spi_init(void) {
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CTRL_BASE_ADDR,
           SPI_CONTROLLER__CTRL__SPIEN_bm | SPI_CONTROLLER__CTRL__OUTPUT_EN_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CFG_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int flash_wren(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, FLASH_CMD_WREN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

static uint8_t flash_rdsr(void) {
    if (spi_wait_ready(TIMEOUT)) return 0xFF;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, FLASH_CMD_RDSR);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1)); // CSAAT held
    if (spi_wait_ready(TIMEOUT)) return 0xFF;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, 1, 0)); // RX 1 byte, release CS
    if (spi_wait_idle(TIMEOUT)) return 0xFF;
    return (uint8_t)(spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR) & 0xFF);
}

static int flash_wip_wait(void) {
    for (int i = 0; i < WIP_POLL_LIM; i++) {
        if (!(flash_rdsr() & FLASH_SR_WIP)) return 0;
    }
    return -1;
}

static int flash_page_program(uint32_t addr, const uint32_t *data, uint32_t nwords) {
    // OT spi_host intended usage: pre-load the whole TX phase into the TX FIFO
    // (cmd+addr word + every data word), then issue ONE TX segment covering all
    // of it (CSAAT=0 releases CS at the end). Chaining a separate CMD per word
    // exercises the segment-boundary FSM path that stalls the host (the FSM holds
    // command_ready low under tx_stall mid-segment); the proven dma_rx path also
    // uses a single TX segment.
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR,
           pack_hdr(FLASH_CMD_PP, addr)); // opcode + 24-bit addr
    for (uint32_t i = 0; i < nwords; i++) {
        spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, data[i]); // data words, LSB-first
    }
    // total TX bytes = 4 (cmd+addr) + nwords*4
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 4 + nwords * 4, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_sector_erase(uint32_t addr) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, pack_hdr(FLASH_CMD_ERASE, addr));
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 0)); // cmd+addr, release CS
    return spi_wait_idle(TIMEOUT);
}

static int flash_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR, pack_hdr(FLASH_CMD_READ, addr));
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 1)); // cmd+addr, CSAAT held
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CMD_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0)); // RX data, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++) {
        out[i] = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR);
    }
    return 0;
}

int main(void) {
    int errors = 0;
    uint32_t rd[MAX_WORDS];
    uint32_t exp[MAX_WORDS];

    sep_outbound_filter_init();
    sep_mbx_puts("SEP SPI OT flash cmd test\n");

    // --- Load the scenario (directed defaults, or cocotb-patched per seed) ---
    if (g_spi1_params[0] != SPI1_PARAM_MAGIC) {
        sep_mbx_puts("FAIL: bad param magic\n");
        return 1;
    }
    uint32_t addr = g_spi1_params[1];
    uint32_t nwords = g_spi1_params[2];
    if (nwords < 1 || nwords > MAX_WORDS) {
        sep_mbx_puts("FAIL: bad nwords ");
        sep_mbx_puthex(nwords);
        sep_mbx_putc('\n');
        return 1;
    }
    for (uint32_t i = 0; i < nwords; i++) {
        exp[i] = g_spi1_params[3 + i]; // stable copy of the (volatile) data words
    }
    sep_mbx_puts("SCENARIO addr=");
    sep_mbx_puthex(addr);
    sep_mbx_puts(" nwords=");
    sep_mbx_puthex(nwords);
    sep_mbx_putc('\n');

    spi_init();

    // --- PROGRAM path: WREN -> PP -> READ == pattern ---
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN timeout\n");
        return 1;
    }
    if (flash_page_program(addr, exp, nwords)) {
        sep_mbx_puts("FAIL: PAGE PROGRAM timeout\n");
        return 1;
    }
    if (flash_read(addr, rd, nwords)) {
        sep_mbx_puts("FAIL: READ timeout\n");
        return 1;
    }
    int prog_ok = 1;
    for (uint32_t i = 0; i < nwords; i++) {
        if (rd[i] != exp[i]) {
            sep_mbx_puts("FAIL: CHK-READ word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(rd[i]);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(exp[i]);
            sep_mbx_putc('\n');
            errors++;
            prog_ok = 0;
        }
    }
    if (prog_ok) {
        sep_mbx_puts("CHK-PROGRAM/CHK-READ PASS: PP + READ match the pattern\n");
    }

    // --- ERASE path: WREN -> ERASE -> READ == 0xFF ---
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN(erase) timeout\n");
        return 1;
    }
    if (flash_sector_erase(addr)) {
        sep_mbx_puts("FAIL: ERASE timeout\n");
        return 1;
    }
    if (flash_read(addr, rd, nwords)) {
        sep_mbx_puts("FAIL: READ(after erase) timeout\n");
        return 1;
    }
    int erase_ok = 1;
    for (uint32_t i = 0; i < nwords; i++) {
        if (rd[i] != 0xFFFFFFFFu) {
            sep_mbx_puts("FAIL: CHK-ERASE word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(rd[i]);
            sep_mbx_putc('\n');
            errors++;
            erase_ok = 0;
        }
    }
    if (erase_ok) {
        sep_mbx_puts("CHK-ERASE PASS: sector erase -> READ all 0xFF\n");
    }

    // --- CHK-NO-ERROR: the OT SPI host saw no error across the whole sequence ---
    uint32_t err = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err != 0) {
        sep_mbx_puts("FAIL: CHK-NO-ERROR ERROR_STATUS=");
        sep_mbx_puthex(err);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-NO-ERROR PASS: OT SPI ERROR_STATUS==0\n");
    }
    sep_mbx_puts("CHK-WIP DEFERRED: RDSR/WIP poll path not enabled in this firmware\n");
    sep_mbx_puts("CHK-DUAL-QUAD DEFERRED: BFM has no 0x3B/0x6B opcode or multi-lane DQ\n");

    if (errors == 0) {
        sep_mbx_puts("PASS: OT SPI flash program/read/erase/no-error all OK\n");
    }
    return errors;
}
