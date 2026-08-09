/*
 * sep_smu_sanity — SMU-level SEP sanity test.
 *
 * Purpose
 * -------
 *   Demonstrates that, with the real SEP RTL instantiated inside the SMU
 *   wrapper (compile_smu_chiplet_sep_rtl, +define+SEP_RTL), the SEP CPU
 *   boots from its TCM and can correctly access several IP modules through
 *   the SEP local fabric.
 *
 * Modules exercised
 * -----------------
 *   1. CPU + STDOUT/printf path        — proves CPU boot + outbound filter
 *                                         + AXI fabric path to STDOUT mailbox
 *                                         (0x80000000) is functional.
 *   2. HMAC (SHA-256 KAT)              — feed "abc", verify against NIST
 *                                         known-answer vector.  Self-contained
 *                                         (no entropy needed).
 *   3. KMAC (SHA3-256 KAT, SW entropy) — feed "abc", verify against NIST
 *                                         known-answer vector.  Uses SW
 *                                         entropy_mode so it does not depend
 *                                         on EDN being available at SMU
 *                                         level.
 *   4. SPI register R/W sanity         — write/readback of SPI mux + clock
 *                                         divider + control registers in the
 *                                         Cadence xSPI controller's register
 *                                         block.  Does NOT trigger SPI
 *                                         init/discovery (no flash model in
 *                                         SMU TB), only proves the fabric
 *                                         routes SEP CPU writes to the SPI
 *                                         control register space.
 *
 * Pass criterion
 * --------------
 *   All four stages succeed → test_pass(0) writes the 2-word magic
 *   sequence to STDOUT (0x80000000) which the cocotb test detects.
 */

#include <stdint.h>
#include <string.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/*
 * NOTE on STDOUT usage
 * --------------------
 * In the SMU testbench the cocotb monitor wakes on every AXI awvalid pulse on
 * the SEP ext_out interface and runs a Python coroutine to inspect the data.
 * Each printf() byte is an 8-bit AXI write and therefore induces enormous
 * cocotb VPI overhead (the prior version stalled the simulator at 27us for
 * tens of minutes of wall time).
 *
 * To keep the test fast we drop printf() entirely and rely solely on the
 * 32-bit magic-word handshake from test_completion.h (test_pass / test_fail).
 * Diagnostic information is preserved by writing failure stage IDs into the
 * SEP outbound STDOUT mailbox as 32-bit stores so they remain visible in
 * waveforms / sim.log without the per-byte overhead.
 */
#define printf(...) ((void)0)
#define STAGE_BEACON(stage_id) \
    do { \
        volatile uint32_t *__b = (volatile uint32_t *)(uintptr_t)STDOUT; \
        *__b = 0xB1B0B0B0u | ((uint32_t)(stage_id)&0xFu); \
        __asm__ volatile("fence" ::: "memory"); \
    } while (0)

/* --------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------ */

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000FFu) << 24) | ((x & 0x0000FF00u) << 8) | ((x & 0x00FF0000u) >> 8) |
           ((x & 0xFF000000u) >> 24);
}

static void to_hex(const uint8_t *in, int n, char *out) {
    static const char *hex = "0123456789abcdef";
    for (int i = 0; i < n; i++) {
        out[2 * i + 0] = hex[(in[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[(in[i] >> 0) & 0xF];
    }
    out[2 * n] = '\0';
}

/* --------------------------------------------------------------------------
 * Stage 1 — HMAC (SHA-256 KAT, "abc")
 * ------------------------------------------------------------------------ */

#define HMAC_TIMEOUT_ITERS 1000000

static int hmac_wait_done_or_idle(void) {
    int t = HMAC_TIMEOUT_ITERS;
    while (t-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) {
            hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
            WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
            return 0;
        }
    }
    printf("    [HMAC] Timeout waiting for completion\n");
    return -1;
}

static int hmac_sha256_abc(uint8_t digest[32]) {
    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 1;
    cfg.f.endian_swap = 0;
    cfg.f.digest_swap = 0;
    cfg.f.digest_size = 1; /* SHA2-256 */
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    /* Feed "abc" — 3 bytes via byte stores so MSG_LENGTH bookkeeping is exact. */
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    const char *msg = "abc";
    for (int i = 0; i < 3; i++) {
        int spins = 0;
        hmac__STATUS_t s;
        do {
            s.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
            if (++spins > 10000) {
                printf("    [HMAC] FIFO full timeout\n");
                return -1;
            }
        } while (s.f.fifo_full);
        *fifo8 = (uint8_t)msg[i];
    }

    cmd.w = 0;
    cmd.f.hash_process = 1;
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    if (hmac_wait_done_or_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        uint32_t raw = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_BASE_ADDR(0) + (i * 4));
        ((uint32_t *)digest)[i] = bswap32(raw);
    }

    /* Cleanup */
    cfg.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR);
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
    return 0;
}

static int stage_hmac(void) {
    printf("\n[Stage 2] HMAC SHA-256 KAT (\"abc\")\n");
    printf("    HMAC base=0x%08x\n", OCH_SEP_TOP_HMAC_BASE_ADDR);

    /* NIST FIPS 180-4 KAT for SHA-256("abc"). */
    static const char *expected_hex =
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    uint8_t digest[32];
    if (hmac_sha256_abc(digest) != 0) {
        printf("    FAIL: HMAC computation error\n");
        return -1;
    }

    char got[65];
    to_hex(digest, 32, got);
    printf("    digest  : %s\n", got);
    printf("    expected: %s\n", expected_hex);

    if (strcmp(got, expected_hex) != 0) {
        printf("    FAIL: HMAC SHA-256 digest mismatch\n");
        return -1;
    }
    printf("    PASS: HMAC SHA-256 digest matches NIST KAT\n");
    return 0;
}

/* --------------------------------------------------------------------------
 * Stage 2 — KMAC (SHA3-256 KAT, "abc"), software entropy mode
 * ------------------------------------------------------------------------ */

#define KMAC_TIMEOUT_ITERS 1000000

/* KMAC CMD codes (from och_sep_top_reg / hjson). */
#define KMAC_CMD_START 29
#define KMAC_CMD_PROCESS 46
#define KMAC_CMD_DONE 22

/* NIST SHA3-256("abc") big-endian reference. */
static const uint32_t sha3_256_abc_ref[8] = {0x3a985da7u, 0x4fe225b2u, 0x045c172du, 0x6bd390bdu,
                                             0x855f086eu, 0x3e9d525bu, 0x46bfe245u, 0x11431532u};

static int kmac_wait_idle(void) {
    int t = KMAC_TIMEOUT_ITERS;
    while (t-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("    [KMAC] Timeout waiting for idle\n");
    return -1;
}

static int kmac_wait_done(void) {
    int t = KMAC_TIMEOUT_ITERS;
    while (t-- > 0) {
        uint32_t intr = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & 0x1u) {
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1u);
            return 0;
        }
    }
    printf("    [KMAC] Timeout waiting for done\n");
    return -1;
}

static int kmac_sha3_256_abc(uint32_t digest_be[8]) {
    if (kmac_wait_idle() != 0) return -1;

    /* SHA3-256, SW entropy_mode (no EDN dependency). */
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = 0x0;         /* SHA3 */
    cfg.f.kstrength = 0x2;    /* L256 → SHA3-256 */
    cfg.f.entropy_mode = 0x2; /* SW */
    cfg.f.msg_endianness = 0;
    cfg.f.state_endianness = 0;
    cfg.f.entropy_ready = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    /* SW-entropy handshake: set entropy_ready, then write 6 seed words. */
    cfg.f.entropy_ready = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    for (int i = 0; i < 6; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEFu + i);
    }

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = KMAC_CMD_START;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    /* Write "abc" — must use byte stores to the SAME word-aligned base
     * (kmac_sha3_256_test fix v2): non-word-aligned byte stores get dropped
     * by the 64→32 AXI DW converter, so use fifo8[0] for all three bytes. */
    {
        volatile uint8_t *fifo8 =
            (volatile uint8_t *)(uintptr_t)(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR);
        fifo8[0] = 'a';
        fifo8[0] = 'b';
        fifo8[0] = 'c';
    }

    cmd.f.cmd = KMAC_CMD_PROCESS;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (kmac_wait_done() != 0) return -1;

    /* Read both shares and XOR to get digest (masking compensation). */
    uint32_t share0[8], share1[8];
    for (int i = 0; i < 8; i++) {
        share0[i] = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4));
        share1[i] = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + 0x100 + (i * 4));
    }

    /* state_endianness=0 → little-endian; convert to BE for KAT compare. */
    for (int i = 0; i < 8; i++) {
        digest_be[i] = bswap32(share0[i] ^ share1[i]);
    }

    cmd.f.cmd = KMAC_CMD_DONE;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    return 0;
}

static int stage_kmac(void) {
    printf("\n[Stage 3] KMAC SHA3-256 KAT (\"abc\", SW entropy)\n");
    printf("    KMAC base=0x%08x\n", OCH_SEP_TOP_KMAC_BASE_ADDR);

    uint32_t digest_be[8];
    if (kmac_sha3_256_abc(digest_be) != 0) {
        printf("    FAIL: KMAC computation error\n");
        return -1;
    }

    printf("    digest  :");
    for (int i = 0; i < 8; i++) printf(" %08x", digest_be[i]);
    printf("\n    expected:");
    for (int i = 0; i < 8; i++) printf(" %08x", sha3_256_abc_ref[i]);
    printf("\n");

    for (int i = 0; i < 8; i++) {
        if (digest_be[i] != sha3_256_abc_ref[i]) {
            printf("    FAIL: word %d mismatch\n", i);
            return -1;
        }
    }
    printf("    PASS: KMAC SHA3-256 digest matches NIST KAT\n");
    return 0;
}

/* --------------------------------------------------------------------------
 * Stage 3 — SPI controller register R/W sanity
 *
 *   The SMU testbench does not instantiate an external SPI flash model, so
 *   we deliberately do NOT trigger init/discovery (which would never assert
 *   init_comp).  Instead we exercise:
 *     (a) SPI mux ctrl  : toggle spi_sel between OT (1) and Cadence (0),
 *                         and cs_force_high.
 *     (b) SPI clk div   : write a custom divider value and read it back.
 *     (c) SPI ctrl      : reset assert/deassert pattern + spi_enable.
 *   These prove that the SEP CPU can reach the SPI controller register
 *   space across the SEP fabric (SEP_EXTERNAL @ 0x2000_0000).
 * ------------------------------------------------------------------------ */

#define SPI_MUX_CTRL_ADDR OCH_SEP_TOP_SEP_EXTERNAL_OCH_SEP_SPI_MUX_CTRL_SPI_MUX_CTRL_BASE_ADDR
#define SPI_CTRL_ADDR OCH_SEP_TOP_SEP_EXTERNAL_OCH_SEP_CDNS_SPI_CTRL_SPI_CTRL_BASE_ADDR
#define SPI_CLK_DIV_CTRL_ADDR \
    OCH_SEP_TOP_SEP_EXTERNAL_OCH_SEP_CDNS_SPI_CTRL_SPI_CLK_DIV_CTRL_BASE_ADDR

static int spi_check_field(const char *name, uint32_t got, uint32_t exp) {
    if (got != exp) {
        printf("    FAIL: %s mismatch: got=0x%08x exp=0x%08x\n", name, got, exp);
        return -1;
    }
    printf("    PASS: %s readback=0x%08x\n", name, got);
    return 0;
}

static int stage_spi_regs(void) {
    printf("\n[Stage 4] SPI controller register R/W sanity\n");
    printf("    SPI_MUX_CTRL @ 0x%08x\n", SPI_MUX_CTRL_ADDR);
    printf("    SPI_CTRL     @ 0x%08x\n", SPI_CTRL_ADDR);
    printf("    SPI_CLK_DIV  @ 0x%08x\n", SPI_CLK_DIV_CTRL_ADDR);

    int errors = 0;

    /* (a) SPI mux ctrl: select Cadence, force CS high. */
    {
        och_sep_spi_mux_ctrl__SPI_MUX_CTRL_t w = {.w = OCH_SEP_SPI_MUX_CTRL__SPI_MUX_CTRL_reset};
        w.f.spi_sel = 0; /* Cadence */
        w.f.cs_force_high = 1;
        WRITE_REG(SPI_MUX_CTRL_ADDR, w.w);

        och_sep_spi_mux_ctrl__SPI_MUX_CTRL_t r = {.w = READ_REG(SPI_MUX_CTRL_ADDR)};
        if (spi_check_field("spi_sel=0", r.f.spi_sel, 0) != 0) errors++;
        if (spi_check_field("cs_force_high=1", r.f.cs_force_high, 1) != 0) errors++;

        /* Toggle to OT to confirm RW field is live. */
        w.f.spi_sel = 1;
        w.f.cs_force_high = 0;
        WRITE_REG(SPI_MUX_CTRL_ADDR, w.w);
        r.w = READ_REG(SPI_MUX_CTRL_ADDR);
        if (spi_check_field("spi_sel=1", r.f.spi_sel, 1) != 0) errors++;
        if (spi_check_field("cs_force_high=0", r.f.cs_force_high, 0) != 0) errors++;
    }

    /* (b) SPI clock divider: write custom value, read back. */
    {
        och_sep_cdns_spi_ctrl__SPI_CLK_DIV_CTRL_t w = {
            .w = OCH_SEP_CDNS_SPI_CTRL__SPI_CLK_DIV_CTRL_reset};
        w.f.clock_divider_value = 32; /* 800/32 = 25 MHz */
        w.f.clock_div_set = 1;
        w.f.clock_dutycycle = 128;
        w.f.clock_div_enable = 1;
        WRITE_REG(SPI_CLK_DIV_CTRL_ADDR, w.w);

        och_sep_cdns_spi_ctrl__SPI_CLK_DIV_CTRL_t r = {.w = READ_REG(SPI_CLK_DIV_CTRL_ADDR)};
        if (spi_check_field("clk_div_value", r.f.clock_divider_value, 32) != 0) errors++;
        if (spi_check_field("clk_dutycycle", r.f.clock_dutycycle, 128) != 0) errors++;
        if (spi_check_field("clk_div_enable", r.f.clock_div_enable, 1) != 0) errors++;
    }

    /* (c) SPI control: reset all sub-blocks, then deassert and enable. */
    {
        och_sep_cdns_spi_ctrl__SPI_CTRL_t w = {.w = OCH_SEP_CDNS_SPI_CTRL__SPI_CTRL_reset};
        w.f.spi_enable = 0;
        w.f.spi_reset_n_n0_scan = 0;
        w.f.spi_ctrl_reg_reset_n_n0_scan = 0;
        w.f.spi_phy_reg_reset_n_n0_scan = 0;
        w.f.spi_phy_reset_n_n0_scan = 0;
        w.f.spi_axi_reset_n_n0_scan = 0;
        w.f.spi_reg_reset_n_n0_scan = 0;
        w.f.spi_xspi_reg_reset_n_n0_scan = 0;
        WRITE_REG(SPI_CTRL_ADDR, w.w);

        och_sep_cdns_spi_ctrl__SPI_CTRL_t r = {.w = READ_REG(SPI_CTRL_ADDR)};
        if (spi_check_field("spi_enable=0", r.f.spi_enable, 0) != 0) errors++;
        if (spi_check_field("spi_reset_n=0", r.f.spi_reset_n_n0_scan, 0) != 0) errors++;

        /* Deassert resets + enable. */
        w.f.spi_enable = 1;
        w.f.spi_reset_n_n0_scan = 1;
        w.f.spi_ctrl_reg_reset_n_n0_scan = 1;
        w.f.spi_phy_reg_reset_n_n0_scan = 1;
        w.f.spi_phy_reset_n_n0_scan = 1;
        w.f.spi_axi_reset_n_n0_scan = 1;
        w.f.spi_reg_reset_n_n0_scan = 1;
        w.f.spi_xspi_reg_reset_n_n0_scan = 1;
        WRITE_REG(SPI_CTRL_ADDR, w.w);

        r.w = READ_REG(SPI_CTRL_ADDR);
        if (spi_check_field("spi_enable=1", r.f.spi_enable, 1) != 0) errors++;
        if (spi_check_field("spi_reset_n=1", r.f.spi_reset_n_n0_scan, 1) != 0) errors++;
    }

    if (errors != 0) {
        printf("    FAIL: SPI register sanity (%d errors)\n", errors);
        return -1;
    }
    printf("    PASS: SPI register sanity (mux + clk_div + ctrl R/W OK)\n");
    return 0;
}

/* --------------------------------------------------------------------------
 * main
 * ------------------------------------------------------------------------ */

int main(void) {
    /* Beacon 0 = main entered; written via raw store BEFORE outbound filter
     * init.  In the standalone SEP TB the outbound filter is open by default
     * and STDOUT writes succeed immediately.  In the SMU TB we cannot tell
     * whether the SoC fabric routes 0x80000000 stores out as ext_out_*,
     * so the very first beacon also serves as a sanity check that the SEP
     * CPU is at least executing instructions.
     *
     * NOTE: writing to STDOUT before sep_outbound_filter_init() will be
     * rejected by the SEP outbound filter (no AXI write reaches the SMU
     * fabric).  We deliberately keep this beacon — if no beacon ever shows
     * up on ext_out, even after filter init, the firmware likely never
     * reached main().  Read sep_stdout_count from cocotb to disambiguate.
     */
    STAGE_BEACON(0);
    sep_outbound_filter_init();
    STAGE_BEACON(1);

    printf("\n========================================\n");
    printf("  SMU-level SEP Sanity Test\n");
    printf("  (boot + HMAC + KMAC + SPI registers)\n");
    printf("========================================\n");

    int errors = 0;

    STAGE_BEACON(2);
    if (stage_hmac() != 0) errors++;
    STAGE_BEACON(3);
    if (stage_kmac() != 0) errors++;
    STAGE_BEACON(4);
    if (stage_spi_regs() != 0) errors++;
    STAGE_BEACON(5);

    printf("\n========================================\n");
    if (errors == 0) {
        printf("  RESULT: ALL STAGES PASSED\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("  RESULT: %d STAGE(S) FAILED\n", errors);
        printf("========================================\n");
        test_fail(errors);
    }

    /* Keep CPU alive after signaling completion. */
    while (1) {
        __asm__ volatile("wfi");
    }
    return 0;
}
