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
// erase and no check depends on a busy flash.
//
// The lane leg then runs the dual and quad commands the parameter block lists:
// the reads 0x3B, 0x6B, 0xBB and 0xEB, each compared word by word with the
// block, and a quad page program 0x32, read back with 0x03 and compared with the
// block. The flash model sits on all four data lanes for this leg.
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

#define MAX_WORDS 16
#define LANE_MAX 5 // lane leg entries: four lane reads and one quad program

// Non-zero SR2 the device model is built with. Must match status_reg2 in
// cocotb/tests/spi/sep_spi_ot_flash_cmd_rand_test.py.
#define FLASH_SR2_SEEDED 0x5Au
#define FLASH_JEDEC_RX 0x0018BA20u

// Reserved command speed encoding: the host must reject the segment with an
// invalid-command error rather than run it.
#define SPI_CMD_SPEED_RESERVED 3u

// Sentinel the cocotb test searches for in the DTCM image to locate this block.
#define SPI1_PARAM_MAGIC 0x5A11C0DEu

// Scenario block. Layout: [0]=magic, [1]=flash addr, [2]=word count (1..MAX_WORDS),
// [3 .. 3+MAX_WORDS-1]=data words (LSB byte sent first), then the lane leg:
// [LANE_BASE]=entry count (0..LANE_MAX), and per entry [opcode, flash addr,
// word count, data words]. A read entry holds the words the flash holds at that
// address; the quad program entry holds the words to program. Volatile so the
// run-time patched values are not folded. The directed defaults stage no lane
// entry: the lane reads need the flash preload that only the cocotb test makes.
#define LANE_BASE (3 + MAX_WORDS)
#define LANE_STRIDE (3 + MAX_WORDS)
volatile uint32_t g_spi1_params[LANE_BASE + 1 + LANE_MAX * LANE_STRIDE] = {
    SPI1_PARAM_MAGIC, 0x000000u, 4u, 0xA5C31234u, 0xDEADBEEFu, 0x0BADF00Du, 0xCAFEBABEu,
};

// Recovers from a latched host error, which blocks further commands until
// cleared. Software reset flushes the command queue and both FIFOs, so the
// segment that caused the error never runs; the host must not leave reset until
// both FIFOs report empty. Software reset clears internal state, not registers,
// so ERROR_STATUS still holds expect_bm after it; then write-one-to-clear
// releases the latch. Returns the number of failures. *residual is the error
// status left afterwards; 0 means the host is released.
static int spi_err_recover(uint32_t expect_bm, uint32_t *residual) {
    int err = 0;
    const uint32_t empty = SPI_CONTROLLER__STATUS__TXEMPTY_bm | SPI_CONTROLLER__STATUS__RXEMPTY_bm;
    uint32_t ctrl = spi_rd(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    spi_wr(SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl | SPI_CONTROLLER__CONTROL__SW_RST_bm);
    uint32_t st = 0;
    int t = SEP_SPI_TIMEOUT;
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
    // The write-one-to-clear below is then the only thing that can release it.
    uint32_t held = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (held != expect_bm) {
        sep_mbx_puts("FAIL: ERROR_STATUS after SW_RST=");
        sep_mbx_puthex(held);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(expect_bm);
        sep_mbx_puts(" (SW_RST clears internal state, not registers)\n");
        err++;
    }
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
    err += spi_err_recover(expect_bm, &residual);
    if (residual != 0) {
        sep_mbx_puts("FAIL: ERROR_STATUS did not W1C-clear, residual=");
        sep_mbx_puthex(residual);
        sep_mbx_putc('\n');
        err++;
    }
    return err;
}

// Prints the PASS line of one lane leg entry: its opcode, lane width, and the
// words and bytes compared.
static void lane_pass_line(const char *chk, uint32_t opcode, uint32_t lanes, uint32_t nwords) {
    sep_mbx_puts(chk);
    sep_mbx_puts(" PASS: op=");
    sep_mbx_puthex(opcode);
    sep_mbx_puts(" width=x");
    sep_mbx_putc((char)('0' + lanes));
    sep_mbx_puts(" words=");
    sep_mbx_puthex(nwords);
    sep_mbx_puts(" bytes=");
    sep_mbx_puthex(nwords * 4u);
    sep_mbx_putc('\n');
}

// Compares nwords read words with the expected words; prints a FAIL line per
// mismatch and returns the mismatch count.
static int lane_compare(const char *chk, uint32_t opcode, const uint32_t *got, const uint32_t *want,
                        uint32_t nwords) {
    int err = 0;
    for (uint32_t i = 0; i < nwords; i++) {
        if (got[i] != want[i]) {
            sep_mbx_puts("FAIL: ");
            sep_mbx_puts(chk);
            sep_mbx_puts(" op=");
            sep_mbx_puthex(opcode);
            sep_mbx_puts(" word ");
            sep_mbx_puthex(i);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(got[i]);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(want[i]);
            sep_mbx_putc('\n');
            err++;
        }
    }
    return err;
}

// Lane leg. CHK-SPI-LANE-READ: each dual or quad read returns, word by word, the
// words the parameter block says the flash holds at that address.
// CHK-SPI-LANE-PROGRAM: a quad page program followed by a standard read returns
// the programmed words. Every entry must also leave ERROR_STATUS at 0. Returns
// the error count.
static int lane_leg(void) {
    uint32_t count = g_spi1_params[LANE_BASE];
    if (count > LANE_MAX) {
        sep_mbx_puts("FAIL: bad lane entry count ");
        sep_mbx_puthex(count);
        sep_mbx_putc('\n');
        return 1;
    }
    sep_mbx_puts("LANE leg entries=");
    sep_mbx_puthex(count);
    sep_mbx_putc('\n');
    int errors = 0;
    for (uint32_t e = 0; e < count; e++) {
        uint32_t base = LANE_BASE + 1u + e * LANE_STRIDE;
        uint32_t opcode = g_spi1_params[base];
        uint32_t addr = g_spi1_params[base + 1u];
        uint32_t nwords = g_spi1_params[base + 2u];
        uint32_t lanes = sep_spi_flash_data_lanes(opcode);
        uint32_t want[MAX_WORDS];
        uint32_t got[MAX_WORDS];
        if (nwords < 1 || nwords > MAX_WORDS || lanes < 2u) {
            sep_mbx_puts("FAIL: bad lane entry op=");
            sep_mbx_puthex(opcode);
            sep_mbx_puts(" nwords=");
            sep_mbx_puthex(nwords);
            sep_mbx_putc('\n');
            errors++;
            continue;
        }
        for (uint32_t i = 0; i < nwords; i++) {
            want[i] = g_spi1_params[base + 3u + i];
            got[i] = ~want[i]; // a read that writes nothing cannot match
        }
        const char *chk = "CHK-SPI-LANE-READ";
        int rc;
        if (opcode == SEP_SPI_OP_QPP) {
            chk = "CHK-SPI-LANE-PROGRAM";
            rc = sep_spi_flash_wren();
            if (rc == 0) rc = sep_spi_flash_program(opcode, addr, want, nwords);
            if (rc == 0) rc = sep_spi_flash_read(SEP_SPI_OP_READ, addr, got, nwords);
        } else {
            rc = sep_spi_flash_read(opcode, addr, got, nwords);
        }
        if (rc) {
            sep_mbx_puts("FAIL: ");
            sep_mbx_puts(chk);
            sep_mbx_puts(" op=");
            sep_mbx_puthex(opcode);
            sep_mbx_puts(" host did not complete the command, rc=");
            sep_mbx_puthex((uint32_t)rc);
            sep_mbx_putc('\n');
            errors++;
            continue;
        }
        int err = lane_compare(chk, opcode, got, want, nwords);
        uint32_t es = spi_rd(SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
        if (es != 0) {
            sep_mbx_puts("FAIL: ");
            sep_mbx_puts(chk);
            sep_mbx_puts(" op=");
            sep_mbx_puthex(opcode);
            sep_mbx_puts(" ERROR_STATUS=");
            sep_mbx_puthex(es);
            sep_mbx_putc('\n');
            err++;
        }
        if (err == 0) {
            lane_pass_line(chk, opcode, lanes, nwords);
        }
        errors += err;
    }
    return errors;
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

    sep_spi_host_init(0);

    uint32_t jedec = 0;
    if (sep_spi_flash_rdreg(SEP_SPI_OP_JEDEC, 3, &jedec)) {
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
    if (sep_spi_flash_wren()) {
        sep_mbx_puts("FAIL: WREN(rdsr) timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_rdsr(&sr)) {
        sep_mbx_puts("FAIL: CHK-RDSR status read timed out after WREN\n");
        errors++;
    } else if (!(sr & SEP_SPI_SR_WEL)) {
        sep_mbx_puts("FAIL: CHK-RDSR WEL not set after WREN\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-RDSR PASS: opcode 0x05 saw WEL after WREN\n");
    }

    if (sep_spi_flash_op(SEP_SPI_OP_WRDI)) {
        sep_mbx_puts("FAIL: WRDI timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_rdsr(&sr)) {
        sep_mbx_puts("FAIL: CHK-WRDI status read timed out after WRDI\n");
        errors++;
    } else if (sr & SEP_SPI_SR_WEL) {
        sep_mbx_puts("FAIL: CHK-WRDI WEL still set after WRDI\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-WRDI PASS: opcode 0x04 cleared a WEL proven set by WREN\n");
    }

    // --- PROGRAM path: WREN -> PP -> READ == pattern ---
    if (sep_spi_flash_wren()) {
        sep_mbx_puts("FAIL: WREN timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_program(SEP_SPI_OP_PP, addr, exp, nwords)) {
        sep_mbx_puts("FAIL: PAGE PROGRAM timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_read(SEP_SPI_OP_READ, addr, rd, nwords)) {
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
        if (sep_spi_flash_read(SEP_SPI_OP_FAST, addr, rd, nwords)) {
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
    if (sep_spi_flash_wren()) {
        sep_mbx_puts("FAIL: WREN(neighbour) timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_program(SEP_SPI_OP_PP, neigh, neigh_pat, nwords)) {
        sep_mbx_puts("FAIL: PAGE PROGRAM(neighbour) timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_read(SEP_SPI_OP_READ, neigh, neigh_rd, nwords)) {
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
    if (sep_spi_flash_wren()) {
        sep_mbx_puts("FAIL: WREN(erase) timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_erase(addr)) {
        sep_mbx_puts("FAIL: ERASE timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_read(SEP_SPI_OP_READ, addr, rd, nwords)) {
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
        if (sep_spi_flash_read(SEP_SPI_OP_READ, neigh, neigh_rd, nwords)) {
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
    if (sep_spi_flash_rdsr(&sr_post)) {
        sep_mbx_puts("FAIL: CHK-WEL-AUTOCLR status read timed out after ERASE\n");
        errors++;
    } else if (sr_post & SEP_SPI_SR_WEL) {
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
    if (sep_spi_flash_program(SEP_SPI_OP_PP, addr, exp, nwords)) {
        sep_mbx_puts("FAIL: CHK-WP-PP unprotected PAGE PROGRAM timeout\n");
        return errors + 1;
    }
    if (sep_spi_flash_read(SEP_SPI_OP_READ, addr, rd, nwords)) {
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
    if (sep_spi_flash_wren()) {
        sep_mbx_puts("FAIL: WREN(rdsr2) timeout\n");
        return errors + 1;
    }
    uint32_t sr2_word = 0;
    int sr2_rc = sep_spi_flash_rdreg(SEP_SPI_OP_RDSR2, 1, &sr2_word);
    uint32_t sr2 = sr2_word & 0xFFu;
    if (sr2_rc) {
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
    if (sep_spi_flash_op(SEP_SPI_OP_WRDI)) {
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
    int rx_drain = SEP_SPI_TIMEOUT;
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
           sep_spi_cmd_word(SPI_CMD_DIR_TX, 1, 0, SPI_CMD_SPEED_STD) |
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
    spi_wr(SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           sep_spi_cmd_word(SPI_CMD_DIR_TX, 1, 0, SPI_CMD_SPEED_STD));
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
    cs_err += spi_err_recover(SPI_CONTROLLER__ERROR_STATUS__CSIDINVAL_bm, &csid_residual);
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
    if (sep_spi_flash_rdreg(SEP_SPI_OP_JEDEC, 3, &jedec_post)) {
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

    // --- Lane leg: dual and quad reads, quad page program ---
    errors += lane_leg();

    if (errors == 0) {
        sep_mbx_puts("PASS: OT SPI flash program/read/erase/protect/error-path all OK\n");
    }
    return errors;
}
