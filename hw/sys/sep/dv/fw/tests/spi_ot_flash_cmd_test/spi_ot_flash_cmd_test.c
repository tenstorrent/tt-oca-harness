// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan SPI host flash command test. Firmware drives the host against
// the flash model through JEDEC ID, write enable and write disable, page
// program, read and fast read, and a sector erase that must leave the adjacent
// sector intact. It then checks that the erase consumed the write enable, issues
// a page program with write enable clear, and reads status register 2. The host
// must report no error across that sequence. Finally each host error class
// (RX underflow, reserved speed, invalid chip select) is provoked alone and
// recovered.
//
// The flash model starts erased and is always ready, so programs need no prior
// erase and no check depends on a busy flash. Dual and quad lanes are not
// modeled.
//
// cocotb patches the scenario block (g_spi1_params, located by SPI1_PARAM_MAGIC)
// per seed. The defaults are the directed scenario, so the image also runs
// standalone.
//
// main returns the error count; crt0.s reports PASS/FAIL. Each checker logs a
// PASS line.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_spi.h"

#define TIMEOUT 200000
#define MAX_WORDS 16

#define FLASH_CMD_WREN 0x06u
#define FLASH_CMD_WRDI 0x04u
#define FLASH_CMD_RDSR 0x05u
#define FLASH_CMD_RDSR2 0x35u
// Non-zero SR2 the device model is built with. Must match status_reg2 in
// cocotb/tests/spi/sep_spi_ot_flash_cmd_rand_test.py.
#define FLASH_SR2_SEEDED 0x5Au
#define FLASH_CMD_JEDEC 0x9Fu
#define FLASH_CMD_PP 0x02u
#define FLASH_CMD_READ 0x03u
#define FLASH_CMD_FAST 0x0Bu
#define FLASH_CMD_ERASE 0x20u
#define FLASH_SR_WEL (1u << 1)
#define FLASH_JEDEC_RX 0x0018BA20u

// Reserved command speed encoding: the host must reject the segment with an
// invalid-command error rather than run it.
#define SPI_CMD_SPEED_RESERVED 3u

// Sentinel the cocotb test searches for in the DTCM image to locate this block.
#define SPI1_PARAM_MAGIC 0x5A11C0DEu

// Scenario block. Layout: [0]=magic, [1]=flash addr, [2]=word count (1..MAX_WORDS),
// [3 .. 3+count-1]=data words (LSB byte sent first). Volatile so the run-time
// patched values are not folded.
volatile uint32_t g_spi1_params[3 + MAX_WORDS] = {
    SPI1_PARAM_MAGIC, 0x000000u, 4u, 0xA5C31234u, 0xDEADBEEFu, 0x0BADF00Du, 0xCAFEBABEu,
};

// The command length field encodes the byte count minus one.
static uint32_t cmd_word(uint32_t direction, uint32_t len_bytes, int csaat) {
    uint32_t v =
        ((direction << SPI_CONTROLLER__COMMAND__DIRECTION_bp) &
         SPI_CONTROLLER__COMMAND__DIRECTION_bm) |
        (((len_bytes - 1) << SPI_CONTROLLER__COMMAND__LEN_bp) & SPI_CONTROLLER__COMMAND__LEN_bm);
    if (csaat) {
        v |= SPI_CONTROLLER__COMMAND__CSAAT_bm;
    }
    return v;
}

static uint32_t pack_hdr(uint32_t opcode, uint32_t addr) {
    // Opcode, then the 24-bit address most-significant byte first, in transmit order
    return (opcode & 0xFF) | (((addr >> 16) & 0xFF) << 8) | (((addr >> 8) & 0xFF) << 16) |
           (((addr >> 0) & 0xFF) << 24);
}

// No select step: the OT SPI host drives the pads directly.

static void spi_init(void) {
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           SPI_CONTROLLER__CONTROL__SPIEN_bm | SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    spi_wr(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int flash_wren(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_WREN);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_wrdi(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_WRDI);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_jedec(uint32_t *out) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_JEDEC);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1));
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, 3, 0));
    if (spi_wait_idle(TIMEOUT)) return -1;
    *out = spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    return 0;
}

// Returns 0 and stores the status byte, or -1 if the controller never responded.
// A timeout is not encoded as 0xFF: WEL is bit 1, so 0xFF would look like WEL set.
static int flash_rdsr_checked(uint8_t *out) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_RDSR);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1)); // hold CS
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, 1, 0)); // RX 1 byte, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    *out = (uint8_t)(spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)) & 0xFF);
    return 0;
}

// Reads status register 2, a device register separate from status register 1.
// Returns 0 and stores the byte, or -1 if the controller never responded.
static int flash_rdsr2(uint8_t *out) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_RDSR2);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1)); // hold CS
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, 1, 0));
    if (spi_wait_idle(TIMEOUT)) return -1;
    *out = (uint8_t)(spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)) & 0xFF);
    return 0;
}

static int flash_page_program(uint32_t addr, const uint32_t *data, uint32_t nwords) {
    // Preload the whole TX phase into the FIFO, then issue one TX segment for all
    // of it: a separate command per word stalls the host at segment boundaries.
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0),
           pack_hdr(FLASH_CMD_PP, addr)); // opcode + 24-bit addr
    for (uint32_t i = 0; i < nwords; i++) {
        spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), data[i]); // data words, LSB-first
    }
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 4 + nwords * 4, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_sector_erase(uint32_t addr) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_ERASE, addr));
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 0)); // command + address, release CS
    return spi_wait_idle(TIMEOUT);
}

static int flash_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_READ, addr));
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 1)); // command + address, hold CS
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0)); // RX data, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++) {
        out[i] = spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    return 0;
}

static int flash_fast_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_FAST, addr));
    spi_wr(SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0); // dummy byte
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 5, 1));
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0));
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++) {
        out[i] = spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    return 0;
}

// Recovers from a latched host error, which blocks further commands until
// cleared. Software reset flushes the command queue and both FIFOs, so the
// segment that caused the error never runs; the host must not leave reset until
// both FIFOs report empty. Then the error latch is cleared. Returns 1 if the
// FIFOs never report empty, else 0. *residual is the error status left
// afterwards; 0 means the host is released.
static int spi_err_recover(uint32_t *residual) {
    int err = 0;
    const uint32_t empty = SPI_CONTROLLER__STATUS__TXEMPTY_bm | SPI_CONTROLLER__STATUS__RXEMPTY_bm;
    uint32_t ctrl = spi_rd(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl | SPI_CONTROLLER__CONTROL__SW_RST_bm);
    uint32_t st = 0;
    int t = TIMEOUT;
    while (t-- > 0) {
        st = spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR);
        if ((st & empty) == empty) break;
    }
    if ((st & empty) != empty) {
        sep_mbx_puts("FAIL: SW_RST held but STATUS.TXEMPTY/RXEMPTY never both set, STATUS=");
        sep_mbx_puthex(st);
        sep_mbx_putc('\n');
        err++;
    }
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl & ~SPI_CONTROLLER__CONTROL__SW_RST_bm);
    spi_wr(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
    *residual = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    return err;
}

// Shared tail for the error injections: the error status must hold exactly the
// provoked class, and recovery must leave it clear.
static int spi_err_expect(uint32_t expect_bm) {
    int err = 0;
    uint32_t es = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (es != expect_bm) {
        sep_mbx_puts("FAIL: ERROR_STATUS=");
        sep_mbx_puthex(es);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(expect_bm);
        sep_mbx_putc('\n');
        err++;
    }
    uint32_t residual = 0;
    err += spi_err_recover(&residual);
    if (residual != 0) {
        sep_mbx_puts("FAIL: ERROR_STATUS did not W1C-clear, residual=");
        sep_mbx_puthex(residual);
        sep_mbx_putc('\n');
        err++;
    }
    return err;
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
        return errors + 1;
    }
    uint32_t addr = g_spi1_params[1];
    uint32_t nwords = g_spi1_params[2];
    if (nwords < 1 || nwords > MAX_WORDS) {
        sep_mbx_puts("FAIL: bad nwords ");
        sep_mbx_puthex(nwords);
        sep_mbx_putc('\n');
        return errors + 1;
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

    uint32_t jedec = 0;
    if (flash_jedec(&jedec)) {
        sep_mbx_puts("FAIL: JEDEC timeout\n");
        return errors + 1;
    }
    if ((jedec & 0x00FFFFFFu) != FLASH_JEDEC_RX) {
        sep_mbx_puts("FAIL: CHK-JEDEC got ");
        sep_mbx_puthex(jedec);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-JEDEC PASS: READ ID 0x9F -> 0x0018ba20\n");
    }

    // Write enable is clear out of reset, so set it first: otherwise the write
    // disable check would pass on a no-op.
    uint8_t sr;
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN(rdsr) timeout\n");
        return errors + 1;
    }
    if (flash_rdsr_checked(&sr)) {
        sep_mbx_puts("FAIL: CHK-RDSR status read timed out after WREN\n");
        errors++;
    } else if (!(sr & FLASH_SR_WEL)) {
        sep_mbx_puts("FAIL: CHK-RDSR WEL not set after WREN\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-RDSR PASS: opcode 0x05 saw WEL after WREN\n");
    }

    if (flash_wrdi()) {
        sep_mbx_puts("FAIL: WRDI timeout\n");
        return errors + 1;
    }
    if (flash_rdsr_checked(&sr)) {
        sep_mbx_puts("FAIL: CHK-WRDI status read timed out after WRDI\n");
        errors++;
    } else if (sr & FLASH_SR_WEL) {
        sep_mbx_puts("FAIL: CHK-WRDI WEL still set after WRDI\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-WRDI PASS: opcode 0x04 cleared a WEL proven set by WREN\n");
    }

    // --- PROGRAM path: WREN -> PP -> READ == pattern ---
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN timeout\n");
        return errors + 1;
    }
    if (flash_page_program(addr, exp, nwords)) {
        sep_mbx_puts("FAIL: PAGE PROGRAM timeout\n");
        return errors + 1;
    }
    if (flash_read(addr, rd, nwords)) {
        sep_mbx_puts("FAIL: READ timeout\n");
        return errors + 1;
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
        if (flash_fast_read(addr, rd, nwords)) {
            sep_mbx_puts("FAIL: FAST READ timeout\n");
            return errors + 1;
        }
        int fast_ok = 1;
        for (uint32_t i = 0; i < nwords; i++) {
            if (rd[i] != exp[i]) {
                sep_mbx_puts("FAIL: CHK-FAST-READ word ");
                sep_mbx_puthex(i);
                sep_mbx_putc('\n');
                errors++;
                fast_ok = 0;
            }
        }
        if (fast_ok) {
            sep_mbx_puts("CHK-FAST-READ PASS: opcode 0x0B returned the programmed pattern\n");
        }
    }

    // Neighbour 4 KiB sector: program it so the erase below cannot pass as a
    // chip-wide wipe.
    uint32_t neigh = addr ^ 0x1000u;
    uint32_t neigh_pat[MAX_WORDS];
    uint32_t neigh_rd[MAX_WORDS];
    for (uint32_t i = 0; i < nwords; i++) {
        neigh_pat[i] = exp[i] ^ 0xFFFFFFFFu;
    }
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN(neighbour) timeout\n");
        return errors + 1;
    }
    if (flash_page_program(neigh, neigh_pat, nwords)) {
        sep_mbx_puts("FAIL: PAGE PROGRAM(neighbour) timeout\n");
        return errors + 1;
    }
    if (flash_read(neigh, neigh_rd, nwords)) {
        sep_mbx_puts("FAIL: READ(neighbour) timeout\n");
        return errors + 1;
    }
    for (uint32_t i = 0; i < nwords; i++) {
        if (neigh_rd[i] != neigh_pat[i]) {
            sep_mbx_puts("FAIL: neighbour sector program word ");
            sep_mbx_puthex(i);
            sep_mbx_putc('\n');
            errors++;
        }
    }

    // --- ERASE path: WREN -> ERASE -> READ == 0xFF, neighbour intact ---
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN(erase) timeout\n");
        return errors + 1;
    }
    if (flash_sector_erase(addr)) {
        sep_mbx_puts("FAIL: ERASE timeout\n");
        return errors + 1;
    }
    if (flash_read(addr, rd, nwords)) {
        sep_mbx_puts("FAIL: READ(after erase) timeout\n");
        return errors + 1;
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
        int neigh_ok = 1;
        if (flash_read(neigh, neigh_rd, nwords)) {
            sep_mbx_puts("FAIL: READ(neighbour after erase) timeout\n");
            return errors + 1;
        }
        for (uint32_t i = 0; i < nwords; i++) {
            if (neigh_rd[i] != neigh_pat[i]) {
                sep_mbx_puts("FAIL: CHK-ERASE neighbour word ");
                sep_mbx_puthex(i);
                sep_mbx_puts(" got ");
                sep_mbx_puthex(neigh_rd[i]);
                sep_mbx_puts(" -- sector erase wiped the adjacent 4KiB sector\n");
                errors++;
                neigh_ok = 0;
            }
        }
        if (neigh_ok) {
            sep_mbx_puts("CHK-ERASE PASS: sector erase -> READ all 0xFF, neighbour "
                         "4KiB sector intact\n");
        }
    }

    // --- CHK-WEL-AUTOCLR: SECTOR ERASE must consume the write-enable latch ---
    // CHK-WP-PP below relies on write enable being clear.
    uint8_t sr_post;
    if (flash_rdsr_checked(&sr_post)) {
        sep_mbx_puts("FAIL: CHK-WEL-AUTOCLR status read timed out after ERASE\n");
        errors++;
    } else if (sr_post & FLASH_SR_WEL) {
        sep_mbx_puts("FAIL: CHK-WEL-AUTOCLR WEL still set after ERASE, sr=");
        sep_mbx_puthex(sr_post);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-WEL-AUTOCLR PASS: SECTOR ERASE consumed the write-enable "
                     "latch (RDSR WEL clear)\n");
    }

    // --- CHK-WP-PP: the controller completes a PAGE PROGRAM issued with WEL clear ---
    // The SEP-side check is that the controller completes the command; cocotb
    // checks that the device saw it at the expected address. The flash model
    // drops a program while write enable is clear, so the erased readback below
    // is model behaviour, not a SEP feature.
    if (flash_page_program(addr, exp, nwords)) {
        sep_mbx_puts("FAIL: CHK-WP-PP unprotected PAGE PROGRAM timeout\n");
        return errors + 1;
    }
    if (flash_read(addr, rd, nwords)) {
        sep_mbx_puts("FAIL: CHK-WP-PP readback timeout\n");
        return errors + 1;
    }
    int wp_ok = 1;
    for (uint32_t i = 0; i < nwords; i++) {
        if (rd[i] != 0xFFFFFFFFu) {
            sep_mbx_puts("FAIL: CHK-WP-PP word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(rd[i]);
            sep_mbx_puts(" -- PAGE PROGRAM landed with WEL clear\n");
            errors++;
            wp_ok = 0;
        }
    }
    if (wp_ok) {
        sep_mbx_puts("CHK-WP-PP PASS: controller completed the WEL-clear PAGE PROGRAM; "
                     "the device model left the sector erased (0xFF, model behaviour)\n");
    }

    // --- CHK-RDSR2: opcode 0x35 reads status register 2, not status register 1 ---
    // With write enable set, status register 1 is non-zero, so a read aliased onto
    // status register 1 fails. The seeded non-zero status register 2 also fails an
    // RX path that returns all-zero.
    if (flash_wren()) {
        sep_mbx_puts("FAIL: WREN(rdsr2) timeout\n");
        return errors + 1;
    }
    uint8_t sr2 = 0;
    if (flash_rdsr2(&sr2)) {
        sep_mbx_puts("FAIL: CHK-RDSR2 status-2 read timed out\n");
        errors++;
    } else if (sr2 != FLASH_SR2_SEEDED) {
        sep_mbx_puts("FAIL: CHK-RDSR2 got ");
        sep_mbx_puthex(sr2);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(FLASH_SR2_SEEDED);
        sep_mbx_puts(" (0x02 is a 0x35-as-0x05 fold; 0x00 is a dead RX)\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-RDSR2 PASS: opcode 0x35 returned the seeded SR2 ");
        sep_mbx_puthex(sr2);
        sep_mbx_puts(", not SR1 0x02 and not an all-zero RX\n");
    }
    if (flash_wrdi()) {
        sep_mbx_puts("FAIL: WRDI(rdsr2) timeout\n");
        return errors + 1;
    }

    // --- CHK-NO-ERROR: the OT SPI host saw no error across the whole sequence ---
    uint32_t err = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err != 0) {
        sep_mbx_puts("FAIL: CHK-NO-ERROR ERROR_STATUS=");
        sep_mbx_puthex(err);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-NO-ERROR PASS: OT SPI ERROR_STATUS==0\n");
    }

    // --- Error paths: provoke each ERROR_STATUS class the host reports ---
    // The injections start from a clean error status. A latched error holds the
    // host until software clears it, so each one must also recover.

    // CHK-ERR-UNDERFLOW: a read with the RX FIFO empty.
    int rx_drain = TIMEOUT;
    while (rx_drain-- > 0 && (spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) &
                              SPI_CONTROLLER__STATUS__RXQD_bm) != 0) {
        (void)spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    if (spi_rd(SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) & SPI_CONTROLLER__STATUS__RXQD_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-UNDERFLOW RX FIFO would not drain; the empty-read "
                     "injection cannot be set up\n");
        return errors + 1;
    }
    (void)spi_rd(SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)); // the empty read
    int uf_err = spi_err_expect(SPI_CONTROLLER__ERROR_STATUS__UNDERFLOW_bm);
    errors += uf_err;
    if (uf_err == 0) {
        sep_mbx_puts("CHK-ERR-UNDERFLOW PASS: RXDATA read with RXQD==0 latched only "
                     "ERROR_STATUS.UNDERFLOW and W1C released it\n");
    }

    // CHK-ERR-CMDINVAL: a COMMAND segment with the reserved SPEED encoding
    // (see SPI_CMD_SPEED_RESERVED).
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 1, 0) |
               (SPI_CMD_SPEED_RESERVED << SPI_CONTROLLER__COMMAND__SPEED_bp));
    int ci_err = spi_err_expect(SPI_CONTROLLER__ERROR_STATUS__CMDINVAL_bm);
    errors += ci_err;
    if (ci_err == 0) {
        sep_mbx_puts("CHK-ERR-CMDINVAL PASS: CMD.SPEED==3 latched only "
                     "ERROR_STATUS.CMDINVAL and W1C released it\n");
    }

    // CHK-ERR-CSIDINVAL: an otherwise legal segment issued with CSID at the
    // top of the 32-bit field. The host compares the whole field, so the
    // stimulus does not assume how many chip-selects the instance decodes.
    spi_wr(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0xFFFFFFFFu);
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    uint32_t csid_es = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0u); // restore before recovery
    int cs_err = 0;
    if (csid_es != SPI_CONTROLLER__ERROR_STATUS__CSIDINVAL_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-CSIDINVAL ERROR_STATUS=");
        sep_mbx_puthex(csid_es);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(SPI_CONTROLLER__ERROR_STATUS__CSIDINVAL_bm);
        sep_mbx_putc('\n');
        cs_err++;
    }
    uint32_t csid_residual = 0;
    cs_err += spi_err_recover(&csid_residual);
    if (csid_residual != 0) {
        sep_mbx_puts("FAIL: CHK-ERR-CSIDINVAL ERROR_STATUS did not W1C-clear, residual=");
        sep_mbx_puthex(csid_residual);
        sep_mbx_putc('\n');
        cs_err++;
    }
    errors += cs_err;
    if (cs_err == 0) {
        sep_mbx_puts("CHK-ERR-CSIDINVAL PASS: CSID=0xFFFFFFFF latched only "
                     "ERROR_STATUS.CSIDINVAL and W1C released it\n");
    }

    // CHK-ERR-RECOVER: the host runs real bus traffic again after the three
    // injections; a host still held by an error returns nothing here.
    uint32_t jedec_post = 0;
    if (flash_jedec(&jedec_post)) {
        sep_mbx_puts("FAIL: CHK-ERR-RECOVER JEDEC timeout after error injection\n");
        errors++;
    } else if ((jedec_post & 0x00FFFFFFu) != FLASH_JEDEC_RX) {
        sep_mbx_puts("FAIL: CHK-ERR-RECOVER JEDEC got ");
        sep_mbx_puthex(jedec_post);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-ERR-RECOVER PASS: READ ID 0x9F -> 0x0018ba20 again after "
                     "underflow/cmdinval/csidinval recovery\n");
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: OT SPI flash program/read/erase/protect/error-path all OK\n");
    }
    return errors;
}
