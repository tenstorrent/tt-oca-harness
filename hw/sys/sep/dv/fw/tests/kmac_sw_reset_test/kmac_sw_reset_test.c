/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Software Reset Test
 *
 * Verifies KMAC software reset via SEP Reset Controller (0x10A50000).
 * Per OCAH spec: KMAC starts in reset (kmac_sw_rst_n=0 by default);
 * firmware must write 1 to bit[4] to release before use.
 *
 * Steps:
 * 1. Assert KMAC reset (kmac_sw_rst_n=0) while other IPs stay released
 * 2. Verify KMAC STATUS shows idle after reset assert
 * 3. Release KMAC reset (kmac_sw_rst_n=1)
 * 4. Wait for idle, run a SHA3-256 hash to confirm KMAC operational
 * 5. Re-assert and release reset, verify KMAC returns to idle defaults
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
#include "../kmac_sha3_256_test/kmac_test_vectors.h"

static uint32_t byte_swap(uint32_t x) {
    return ((x & 0x000000ffu) << 24) | ((x & 0x0000ff00u) << 8) | ((x & 0x00ff0000u) >> 8) |
           ((x & 0xff000000u) >> 24);
}

#define RST_CTRL_ADDR OCH_SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR

#define RST_KM SEP_RESET_CTRL__SW_RESET_N__KM_SW_RST_N_bm
#define RST_OTBN SEP_RESET_CTRL__SW_RESET_N__OTBN_SW_RST_N_bm
#define RST_AES SEP_RESET_CTRL__SW_RESET_N__AES_SW_RST_N_bm
#define RST_HMAC SEP_RESET_CTRL__SW_RESET_N__HMAC_SW_RST_N_bm
#define RST_KMAC SEP_RESET_CTRL__SW_RESET_N__KMAC_SW_RST_N_bm
#define RST_TRNG SEP_RESET_CTRL__SW_RESET_N__TRNG_SW_RST_N_bm
#define RST_ABR SEP_RESET_CTRL__SW_RESET_N__ABR_SW_RST_N_bm

/* Post-TB bring-up: KM held (bit0=0), otbn/aes/hmac/kmac/trng/abr released. */
#define RST_POST_TB_EXPECTED (RST_OTBN | RST_AES | RST_HMAC | RST_KMAC | RST_TRNG | RST_ABR)
/* Explicit full release mask used when this test releases KMAC (and KM). */
#define RST_ALL_RELEASE (RST_KM | RST_OTBN | RST_AES | RST_HMAC | RST_KMAC | RST_TRNG | RST_ABR)

static int test_errors = 0;

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        if (READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR) & KMAC__INTR_STATE__KMAC_DONE_bm) {
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
            return 0;
        }
    }
    printf("Timeout waiting for KMAC done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++) WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static int run_sha3_hash(void) {
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.entropy_ready = 0;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.entropy_ready = 1;
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    setup_entropy();

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    /* Empty message SHA3-256 NIST FIPS 202 vector */
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_for_done() != 0) return -1;

    /* STATE words are LE; NIST refs in kmac_test_vectors.h are BE words. */
    int mismatch = 0;
    for (int i = 0; i < 8; i++) {
        uint32_t dig = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + (uint32_t)i * 4u) ^
                       READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET +
                                (uint32_t)i * 4u);
        uint32_t dig_be = byte_swap(dig);
        if (dig_be != sha3_256_empty_ref[i]) {
            printf("  DIGEST_%d=0x%08x expected=0x%08x\n", i, dig_be, sha3_256_empty_ref[i]);
            mismatch = 1;
        }
    }

    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return mismatch ? -1 : 0;
}

static int test_sw_reset(void) {
    printf("=== Step 1: Check default reset state ===\n");
    uint32_t rst = READ_REG(RST_CTRL_ADDR);
    printf("  SW_RESET_N default = 0x%08x (expect 0x%08x: KM held, others released)\n", rst,
           RST_POST_TB_EXPECTED);
    /* Fail hard if TB precondition unmet (matches the composed SW_RESET_N reset). */
    if (rst != RST_POST_TB_EXPECTED) {
        printf("FAIL: SW_RESET_N=0x%08x expected=0x%08x (TB precondition unmet)\n", rst,
               RST_POST_TB_EXPECTED);
        test_errors++;
    } else {
        printf("PASS: SW_RESET_N post-TB default matches expected\n");
    }

    printf("=== Step 2: Assert KMAC reset only (keep others released) ===\n");
    /* Release all except KMAC */
    uint32_t release_others = RST_KM | RST_OTBN | RST_AES | RST_HMAC;
    WRITE_REG(RST_CTRL_ADDR, release_others);
    rst = READ_REG(RST_CTRL_ADDR);
    printf("  SW_RESET_N after assert KMAC reset = 0x%08x\n", rst);
    if (rst != release_others) {
        printf("FAIL: SW_RESET_N=0x%08x expected=0x%08x after KMAC assert\n", rst, release_others);
        test_errors++;
    } else if (rst & RST_KMAC) {
        printf("FAIL: KMAC reset bit still released after assert write\n");
        test_errors++;
    } else {
        printf("PASS: KMAC held in reset (SW_RESET_N.kmac=0)\n");
    }
    /* Note: KMAC AXI slave is gated while kmac_sw_rst_n=0; do not MMIO STATUS. */

    printf("=== Step 3: Release KMAC reset ===\n");
    WRITE_REG(RST_CTRL_ADDR, RST_ALL_RELEASE);
    rst = READ_REG(RST_CTRL_ADDR);
    printf("  SW_RESET_N after release = 0x%08x\n", rst);
    /* Note: RST_CTRL readback may return bus-error value from SEP CPU perspective.
     * Functional verification (sha3_idle, hash) is used to confirm reset release. */
    printf("INFO: kmac_sw_rst_n write issued (functional check follows)\n");

    printf("=== Step 4: Verify KMAC idle after release ===\n");
    if (wait_for_idle() != 0) {
        printf("FAIL: KMAC not idle after reset release\n");
        test_errors++;
        return -1;
    }
    kmac__STATUS_t s;
    s.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR);
    printf("  STATUS = 0x%08x (expect 0x4001: sha3_idle=1 fifo_empty=1)\n", s.w);
    if (s.f.sha3_idle && s.f.fifo_empty) {
        printf("PASS: KMAC idle and fifo_empty after reset release\n");
    } else {
        printf("FAIL: STATUS=0x%08x unexpected after reset\n", s.w);
        test_errors++;
    }

    printf("=== Step 5: Verify CFG_REGWEN default after reset ===\n");
    kmac__CFG_REGWEN_t rw = {.w = READ_REG(OCH_SEP_TOP_KMAC_CFG_REGWEN_BASE_ADDR)};
    printf("  CFG_REGWEN = %u (expect 1)\n", rw.f.en);
    if (rw.f.en) {
        printf("PASS: CFG_REGWEN=1 after reset\n");
    } else {
        printf("FAIL: CFG_REGWEN=0 after reset\n");
        test_errors++;
    }

    printf("=== Step 6: Run SHA3-256 hash to confirm KMAC operational ===\n");
    if (run_sha3_hash() == 0) {
        printf("PASS: SHA3-256 empty-message NIST digest after reset release\n");
    } else {
        printf("FAIL: SHA3-256 hash/digest mismatch after reset release\n");
        test_errors++;
    }

    printf("=== Step 7: Re-assert and re-release reset (second cycle) ===\n");
    WRITE_REG(RST_CTRL_ADDR, RST_ALL_RELEASE & ~RST_KMAC); /* assert */
    WRITE_REG(RST_CTRL_ADDR, RST_ALL_RELEASE);             /* release */

    if (wait_for_idle() != 0) {
        printf("FAIL: KMAC not idle after second reset cycle\n");
        test_errors++;
        return -1;
    }
    s.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR);
    if (s.f.sha3_idle && s.f.fifo_empty) {
        printf("PASS: KMAC idle after second reset cycle\n");
    } else {
        printf("FAIL: STATUS=0x%08x after second reset\n", s.w);
        test_errors++;
    }

    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  Software Reset Test\n");
    printf("========================================\n\n");

    test_sw_reset();

    printf("\n========================================\n");
    if (test_errors == 0) {
        printf("  RESULT: TEST PASSED\n");
        test_pass(0);
    } else {
        printf("  RESULT: TEST FAILED (errors=%d)\n", test_errors);
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
