// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP OpenTitan-SPI flash command-breadth firmware test. Direct cpu-firmware port
// of the reference spi_ot_flash_write_read_test + spi_ot_flash_sector_erase_test,
// driving the OT SPI host (@ 0x10B0_0000) against the OcahSpiFlash BFM.
// Firmware-mode (like every reference spi_ot flash test and sep_spi_ot_dma_rx) --
// the OT spi_host multi-command flash sequence runs from the EL2 CPU, not the
// no_cpu AXI splice.
//
// Flow: JEDEC, then WREN -> RDSR (WEL set) -> WRDI -> RDSR (WEL clear), then
// WREN -> PAGE PROGRAM -> READ + verify == pattern -> FAST_READ, then neighbour
// PAGE PROGRAM, then WREN -> SECTOR ERASE -> READ == 0xFF with neighbour intact.
// Then the write-protect and status-register-2 breadth: RDSR proves the erase
// consumed WEL, a PAGE PROGRAM with WEL clear must NOT land, and RDSR2 (0x35)
// must return SR2 rather than the SR1 value. ERROR_STATUS checked
// == 0 across all of that. Finally the host error classes are provoked one at a
// time (underflow, reserved CMD.SPEED, out-of-range CSID) and recovered.
//
// The flash model is instant-ready, so WIP is never observed set. There is
// no WIP checker: a "WIP clear" assertion could not fail. Dual and
// quad lanes are not modeled, so no checker here covers them.
//
// The BFM memory inits to 0xFF (erased), so PAGE PROGRAM (NOR-AND) writes the
// pattern directly.
//
// RANDOMIZATION ([RAND-REP]): the scenario (flash address, word count, data) is
// held in the g_spi1_params block below. The committed defaults are the directed
// scenario, so the firmware runs standalone; the cocotb test (single source of
// randomness, seeded by the run seed) overwrites the block in the staged DTCM
// image per run by locating the SPI1_PARAM_MAGIC sentinel. The firmware just
// consumes the block, so the same compiled image covers every seed.
//
// main returns the error count; crt0.s emits PASS (0xCAFEBABE) / FAIL
// (0xDEADBEEF) magic on the 0x8000_0000 mailbox. Each checker logs a positive
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

// CMD.SPEED == 3 is reserved; the host must reject the segment rather than run
// it (spi_host.sv test_speed_inval).
#define SPI_CMD_SPEED_RESERVED 3u

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

// LEN encodes byte count - 1. Every field goes through the generated position
// and mask: the register layout is owned by the OpenTitan spi_host block, and
// hand-packed bit positions silently break when it changes.
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
    // byte0=opcode, byte1=addr[23:16], byte2=addr[15:8], byte3=addr[7:0]
    return (opcode & 0xFF) | (((addr >> 16) & 0xFF) << 8) | (((addr >> 8) & 0xFF) << 16) |
           (((addr >> 0) & 0xFF) << 24);
}

// No pad-mux step: this DUT drives the OT SPI host onto the pads directly.

static void spi_init(void) {
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           SPI_CONTROLLER__CONTROL__SPIEN_bm | SPI_CONTROLLER__CONTROL__OUTPUT_EN_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR, SPI_CFG_CLKDIV9_CSN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
}

static int flash_wren(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_WREN);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_wrdi(void) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_WRDI);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_jedec(uint32_t *out) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_JEDEC);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 1));
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, 3, 0));
    if (spi_wait_idle(TIMEOUT)) return -1;
    *out = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    return 0;
}

// Returns 0 and stores the status byte, or -1 if the controller never responded.
// A timeout is not encoded as 0xFF: WEL is bit 1, so 0xFF would look like WEL set.
static int flash_rdsr_checked(uint8_t *out) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_RDSR);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 1, 1)); // CSAAT held
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, 1, 0)); // RX 1 byte, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    *out = (uint8_t)(spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)) & 0xFF);
    return 0;
}

// RDSR2 (0x35). A separate device register from RDSR (0x05): the flash model
// answers 0x35 from status_reg2 and 0x05 from status_reg1 | WEL
// (hw/common/dv/vip/ocah_spi_vip/cocotb/ocah_spi_flash.py). Returns 0 and stores
// the byte, or -1 if the controller never responded.
static int flash_rdsr2(uint8_t *out) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), FLASH_CMD_RDSR2);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 1, 1)); // CSAAT held
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, 1, 0));
    if (spi_wait_idle(TIMEOUT)) return -1;
    *out = (uint8_t)(spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)) & 0xFF);
    return 0;
}

static int flash_page_program(uint32_t addr, const uint32_t *data, uint32_t nwords) {
    // OT spi_host intended usage: pre-load the whole TX phase into the TX FIFO
    // (cmd+addr word + every data word), then issue ONE TX segment covering all
    // of it (CSAAT=0 releases CS at the end). Chaining a separate CMD per word
    // exercises the segment-boundary FSM path that stalls the host (the FSM holds
    // command_ready low under tx_stall mid-segment); the dma_rx path also
    // uses a single TX segment.
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0),
           pack_hdr(FLASH_CMD_PP, addr)); // opcode + 24-bit addr
    for (uint32_t i = 0; i < nwords; i++) {
        spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), data[i]); // data words, LSB-first
    }
    // total TX bytes = 4 (cmd+addr) + nwords*4
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4 + nwords * 4, 0));
    return spi_wait_idle(TIMEOUT);
}

static int flash_sector_erase(uint32_t addr) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_ERASE, addr));
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 0)); // cmd+addr, release CS
    return spi_wait_idle(TIMEOUT);
}

static int flash_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_READ, addr));
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_TX, 4, 1)); // cmd+addr, CSAAT held
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
           cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0)); // RX data, release CS
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++) {
        out[i] = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    return 0;
}

static int flash_fast_read(uint32_t addr, uint32_t *out, uint32_t nwords) {
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), pack_hdr(FLASH_CMD_FAST, addr));
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR(0), 0); // dummy byte
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 5, 1));
    if (spi_wait_ready(TIMEOUT)) return -1;
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_RX, nwords * 4, 0));
    if (spi_wait_idle(TIMEOUT)) return -1;
    for (uint32_t i = 0; i < nwords; i++) {
        out[i] = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    return 0;
}

// The OT SPI host holds its core disabled while ANY ERROR_STATUS bit is latched
// (spi_host.sv: en = en_sw & ~enb_error, enb_error = ERROR_STATUS.intr).
// Recovery is CTRL.SW_RST -- which flushes the command queue and both data FIFOs,
// so the segment that provoked the error cannot run on the bus once the core is
// re-enabled -- followed by the W1C of ERROR_STATUS. Returns what ERROR_STATUS
// still reads afterwards; 0 means the host is released.
static uint32_t spi_err_recover(void) {
    uint32_t ctrl = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR, ctrl | SPI_CONTROLLER__CONTROL__SW_RST_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CONTROL_BASE_ADDR,
           ctrl & ~SPI_CONTROLLER__CONTROL__SW_RST_bm);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR, 0xFFFFFFFFu);
    return spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
}

// Shared tail for the three error injections: ERROR_STATUS must read EXACTLY the
// one bit the provoked class owns (no bit missing, no other class collaterally
// latched), and the SW_RST + W1C recovery must leave it clear. Both values are
// read back from the host, and both are compared against literals that do not
// come from the injection.
static int spi_err_expect(uint32_t expect_bm) {
    int err = 0;
    uint32_t es = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (es != expect_bm) {
        sep_mbx_puts("FAIL: ERROR_STATUS=");
        sep_mbx_puthex(es);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(expect_bm);
        sep_mbx_putc('\n');
        err++;
    }
    uint32_t residual = spi_err_recover();
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

    // WEL is 0 out of reset, so WRDI must run on a WEL that is KNOWN set -- otherwise
    // the "cleared" check asserts 0 after 0 and passes on a no-op opcode.
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
    // A WEL left set leaves the device armed for a program nobody asked for,
    // which is exactly the state CHK-WP-PP below relies on being absent. WIP is
    // not a checker here: the device model is instant-ready and
    // never raises it, so a "WIP clear" assertion could not fail.
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

    // --- CHK-WP-PP: a PAGE PROGRAM issued with WEL clear must not land ---
    // WEL is clear here (the erase above consumed it and CHK-WEL-AUTOCLR proved
    // so), and the sector reads erased. A device that programmed anyway would
    // return the pattern instead of 0xFF -- the readback is over the same SPI
    // datapath as every other check, not an internal peek.
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
        sep_mbx_puts("CHK-WP-PP PASS: PAGE PROGRAM with WEL clear left the sector "
                     "erased (0xFF)\n");
    }

    // --- CHK-RDSR2: opcode 0x35 reads status register 2, not status register 1 ---
    // Run it with WEL KNOWN set, so SR1 reads 0x02: a 0x35 decoded as (or aliased
    // onto) 0x05 returns 0x02 and fails. The device model is built with a
    // non-zero SR2 (FLASH_SR2_SEEDED, matching status_reg2 in
    // sep_spi_ot_flash_cmd_rand_test.py) so that an RX path that returns all-zero
    // -- a stuck MISO, a byte count that never shifts -- fails here too. An SR2
    // of 0x00 would let that dead path pass.
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
    uint32_t err = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    if (err != 0) {
        sep_mbx_puts("FAIL: CHK-NO-ERROR ERROR_STATUS=");
        sep_mbx_puthex(err);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-NO-ERROR PASS: OT SPI ERROR_STATUS==0\n");
    }

    // --- Error paths: provoke each ERROR_STATUS class the host reports ---
    // Everything above ran with ERROR_STATUS == 0, so these injections start from
    // a clean latch. Each one must set EXACTLY its own bit and nothing else, and
    // must be recoverable; the host keeps its core disabled until software clears
    // the latch, so an unrecoverable error would strand every later transfer.

    // CHK-ERR-UNDERFLOW: reading RXDATA with the RX FIFO empty
    // (spi_host.sv: error_underflow = rx_ready & ~rx_valid).
    int rx_drain = TIMEOUT;
    while (rx_drain-- > 0 && (spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) &
                              SPI_CONTROLLER__STATUS__RXQD_bm) != 0) {
        (void)spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0));
    }
    if (spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_STATUS_BASE_ADDR) & SPI_CONTROLLER__STATUS__RXQD_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-UNDERFLOW RX FIFO would not drain; the empty-read "
                     "injection cannot be set up\n");
        return errors + 1;
    }
    (void)spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_RXDATA_BASE_ADDR(0)); // the empty read
    int uf_err = spi_err_expect(SPI_CONTROLLER__ERROR_STATUS__UNDERFLOW_bm);
    errors += uf_err;
    if (uf_err == 0) {
        sep_mbx_puts("CHK-ERR-UNDERFLOW PASS: RXDATA read with RXQD==0 latched only "
                     "ERROR_STATUS.UNDERFLOW and W1C released it\n");
    }

    // CHK-ERR-CMDINVAL: a COMMAND segment with the reserved SPEED encoding
    // (spi_host.sv: test_speed_inval on CMD.SPEED == 3).
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR,
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
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0xFFFFFFFFu);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_COMMAND_BASE_ADDR, cmd_word(SPI_CMD_DIR_TX, 1, 0));
    uint32_t csid_es = spi_rd(OCH_SEP_TOP_SPI_CONTROLLER_ERROR_STATUS_BASE_ADDR);
    spi_wr(OCH_SEP_TOP_SPI_CONTROLLER_CSID_BASE_ADDR, 0u); // restore before recovery
    int cs_err = 0;
    if (csid_es != SPI_CONTROLLER__ERROR_STATUS__CSIDINVAL_bm) {
        sep_mbx_puts("FAIL: CHK-ERR-CSIDINVAL ERROR_STATUS=");
        sep_mbx_puthex(csid_es);
        sep_mbx_puts(" exp ");
        sep_mbx_puthex(SPI_CONTROLLER__ERROR_STATUS__CSIDINVAL_bm);
        sep_mbx_putc('\n');
        cs_err++;
    }
    uint32_t csid_residual = spi_err_recover();
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
    // injections. A host left disabled by a stuck ERROR_STATUS returns nothing
    // here, so this is the positive proof that the recovery above is real and
    // that the flushed bogus segments never reached the device.
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
