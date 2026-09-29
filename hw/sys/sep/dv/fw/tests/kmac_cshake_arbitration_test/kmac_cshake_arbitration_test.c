/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC cSHAKE Arbitration / Back-to-Back Test
 *
 * Verifies that the KMAC cSHAKE datapath handles sequential SW-initiated
 * operations correctly with no state leakage between runs.
 *
 * cSHAKE in this test: SHAKE mode (mode=0x2), L128 security, kmac_en=0.
 * All operations use sideload=0 (SW key path disabled; no key for pure cSHAKE).
 *
 * Test flow (4 sequential cSHAKE-128 operations):
 *
 * Op A — message "msg_a" (5 bytes)
 * Op B — message "msg_b" (5 bytes, 1 byte differs from msg_a)
 * Op C — message "msg_a" again (must match Op A output)
 * Op D — message "msg_a" again (must match Op A output)
 *
 * Checker summary (6 items):
 * [1] Op A completes without timeout
 * [2] Op B completes without timeout
 * [3] Op C completes without timeout
 * [4] Op D completes without timeout
 * [5] digest_B != digest_A  (different inputs produce different outputs)
 * [6] digest_C == digest_A  (same inputs produce same output; determinism)
 *
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
/* ------------------------------------------------------------------ */
/* KMAC helpers                                                        */
/* ------------------------------------------------------------------ */

static int wait_idle(void) {
    int t = 2000000;
    while (t-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("  ERROR: KMAC idle timeout\n");
    return -1;
}

static int wait_done(void) {
    int t = 2000000;
    while (t-- > 0) {
        uint32_t intr = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & KMAC__INTR_STATE__KMAC_DONE_bm) {
            WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm); /* W1C */
            return 0;
        }
    }
    printf("  ERROR: KMAC done timeout\n");
    return -1;
}

/*
 * Configure for pure cSHAKE-128 (no KMAC key) with software entropy.
 */
static void configure_cshake(void) {
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_CSHAKE;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L128;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.sideload = 0;
    cfg.f.entropy_ready = 0;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    for (int i = 0; i < SEP_KMAC_NUM_SEED_WORDS; i++) {
        WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEFu + (uint32_t)i);
    }
}

/* Set customization string prefix = encode_string("csh") for cSHAKE */
static void write_cshake_prefix(void) {
    /* encode_string("csh"): left_encode(3*8) || "csh"
     * left_encode(24) = 0x01 0x18
     * + 'c'=0x63, 's'=0x73, 'h'=0x68
     * as LE bytes: 0x63 0x73 0x68 (0x18 padded)
     * packed 32-bit LE word0: 0x63181801 (bytestream), word1: 0x00007368
     * Using a simple fixed prefix for determinism */
    WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(0), 0x63181801U);
    WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(1), 0x00007368U); /* not BASE(0)+4 */
    for (int i = 2; i < 11; i++) WRITE_REG(SEP_TOP_KMAC_PREFIX_BASE_ADDR(i), 0);
}

/*
 * Run one cSHAKE-128 operation.
 * msg_words: array of 32-bit LE words
 * msg_count: number of words to write
 * Reads 8-word (256-bit) output from STATE.
 */
static int run_cshake_op(const uint32_t *msg_words, int msg_count, uint32_t out[8]) {
    kmac__CMD_t cmd = {.w = 0};

    cmd.f.cmd = SEP_KMAC_CMD_START; /* CmdStart */
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    for (int i = 0; i < msg_count; i++) WRITE_REG(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR, msg_words[i]);

    cmd.f.cmd = SEP_KMAC_CMD_PROCESS; /* CmdProcess */
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (wait_done() != 0) return -1;

    for (int i = 0; i < 8; i++)
        out[i] = READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4))) ^
                 READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + (i * 4)));

    cmd.f.cmd = SEP_KMAC_CMD_DONE; /* CmdDone */
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    return 0;
}

static void print_digest(const char *label, const uint32_t d[8]) {
    printf("  %s: ", label);
    for (int i = 0; i < 8; i++) printf("%08x ", d[i]);
    printf("\n");
}

/* ------------------------------------------------------------------ */
/* Main                                                                */
/* ------------------------------------------------------------------ */

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  cSHAKE Arbitration Test\n");
    printf("  4 back-to-back cSHAKE-128 operations\n");
    printf("========================================\n\n");

    int errors = 0;
    uint32_t digest_a[8], digest_b[8], digest_c[8], digest_d[8];

    /*
     * Messages (two 32-bit words each, distinct between A and B):
     * msg_a = {0xAAAAAAAA, 0x55555555}  (8 bytes)
     * msg_b = {0xBBBBBBBB, 0x44444444}  (8 bytes)
     */
    static const uint32_t msg_a[2] = {0xAAAAAAAAU, 0x55555555U};
    static const uint32_t msg_b[2] = {0xBBBBBBBBU, 0x44444444U};

    /* --- Op A: message msg_a --- */
    printf("=== Op A: cSHAKE-128(msg_a=[0xAAAAAAAA, 0x55555555]) ===\n");
    if (wait_idle() != 0) {
        errors++;
        goto done;
    }
    configure_cshake();
    write_cshake_prefix();
    if (run_cshake_op(msg_a, 2, digest_a) != 0) {
        printf("  CHK[1] FAIL: Op A timeout\n");
        errors++;
        goto done;
    }
    printf("  CHK[1] PASS: Op A completed\n");
    print_digest("A", digest_a);

    /* --- Op B: message msg_b --- */
    printf("\n=== Op B: cSHAKE-128(msg_b=[0xBBBBBBBB, 0x44444444]) ===\n");
    if (wait_idle() != 0) {
        errors++;
        goto done;
    }
    configure_cshake();
    write_cshake_prefix();
    if (run_cshake_op(msg_b, 2, digest_b) != 0) {
        printf("  CHK[2] FAIL: Op B timeout\n");
        errors++;
        goto done;
    }
    printf("  CHK[2] PASS: Op B completed\n");
    print_digest("B", digest_b);

    /* --- Op C: message msg_a (should match Op A) --- */
    printf("\n=== Op C: cSHAKE-128(msg_a) [must match Op A] ===\n");
    if (wait_idle() != 0) {
        errors++;
        goto done;
    }
    configure_cshake();
    write_cshake_prefix();
    if (run_cshake_op(msg_a, 2, digest_c) != 0) {
        printf("  CHK[3] FAIL: Op C timeout\n");
        errors++;
        goto done;
    }
    printf("  CHK[3] PASS: Op C completed\n");
    print_digest("C", digest_c);

    /* --- Op D: message msg_a again (must also match Op A) --- */
    printf("\n=== Op D: cSHAKE-128(msg_a) [must match Op A] ===\n");
    if (wait_idle() != 0) {
        errors++;
        goto done;
    }
    configure_cshake();
    write_cshake_prefix();
    if (run_cshake_op(msg_a, 2, digest_d) != 0) {
        printf("  CHK[4] FAIL: Op D timeout\n");
        errors++;
        goto done;
    }
    printf("  CHK[4] PASS: Op D completed\n");
    print_digest("D", digest_d);

    /* --- Checker [5]: A != B --- */
    printf("\n=== CHK[5]: digest_B differs from digest_A ===\n");
    int a_ne_b = 0;
    for (int i = 0; i < 8; i++)
        if (digest_a[i] != digest_b[i]) {
            a_ne_b = 1;
            break;
        }
    if (a_ne_b) {
        printf("  CHK[5] PASS: distinct inputs → distinct digests\n");
    } else {
        printf("  CHK[5] FAIL: digest_A == digest_B (collision or state leak)\n");
        errors++;
    }

    /* --- Checker [6]: C == A --- */
    printf("=== CHK[6]: digest_C matches digest_A (determinism) ===\n");
    int c_eq_a = 1;
    for (int i = 0; i < 8; i++)
        if (digest_c[i] != digest_a[i]) {
            c_eq_a = 0;
            break;
        }
    if (c_eq_a) {
        printf("  CHK[6] PASS: same input → same output (deterministic)\n");
    } else {
        printf("  CHK[6] FAIL: digest_C != digest_A (state leaked between ops)\n");
        print_digest("A", digest_a);
        print_digest("C", digest_c);
        errors++;
    }

    /* Also verify D == A (same check, different run) — FAIL-ON mismatch */
    int d_eq_a = 1;
    for (int i = 0; i < 8; i++)
        if (digest_d[i] != digest_a[i]) {
            d_eq_a = 0;
            break;
        }
    if (d_eq_a) {
        printf("  CHK[6b] PASS: digest_D matches digest_A\n");
    } else {
        printf("  CHK[6b] FAIL: digest_D != digest_A\n");
        print_digest("A", digest_a);
        print_digest("D", digest_d);
        errors++;
    }

done:
    printf("\n========================================\n");
    if (errors == 0) {
        printf("=== TEST PASSED (%d errors) ===\n", errors);
        test_pass(0);
    } else {
        printf("=== TEST FAILED (%d errors) ===\n", errors);
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
