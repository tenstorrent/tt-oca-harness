/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES Basic Smoke Test (FUNC-001)
 *
 * Coverage (per test plan):
 *  - AES-128 ECB one-block encrypt + decrypt roundtrip
 *  - AES-128 CBC three-block encrypt with chaining verification
 *  - Automatic flow control: INPUT_READY / OUTPUT_VALID handshaking
 *  - Alert status monitoring
 *
 * Register write ordering (same as aes_test.c):
 *   CTRL_SHADOWED -> wait_idle -> KEY -> wait_idle -> IV -> wait_input_ready
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_aes_init.h"
#include "aes_test_util.h"

/* ------------------------------------------------------------------ */
/* Test Vectors (NIST SP 800-38A, AES-128)                            */
/* ------------------------------------------------------------------ */

static const uint32_t test_key[4] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09};

/* ECB uses zero IV (not used by hardware, written for completeness). */
static const uint32_t zero_iv[4] = {0x00000000, 0x00000000, 0x00000000, 0x00000000};

static const uint32_t cbc_iv[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};

/* NIST F.1 ECB block #1 */
static const uint32_t ecb_pt[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};
static const uint32_t ecb_ct_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

/* NIST F.2 CBC 3-block */
static const uint32_t cbc_pt[3][4] = {{0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373},
                                      {0x578a2dae, 0x9cac031e, 0xac6fb79e, 0x518eaf45},
                                      {0x461cc830, 0x11e45ca3, 0x19c1fbe5, 0xef520a1a}};
static const uint32_t cbc_ct_exp[3][4] = {{0xacab4976, 0x46b21981, 0x9b8ee9ce, 0x7d19e912},
                                          {0x9bcb8650, 0xee197250, 0x3a11db95, 0xb2787691},
                                          {0xb8d6be73, 0x3b74c1e3, 0x9ee61671, 0x16952222}};

/* ------------------------------------------------------------------ */
/* ECB Encrypt + Decrypt Roundtrip                                    */
/* ------------------------------------------------------------------ */

static int run_ecb_roundtrip(void) {
    uint32_t out[4];

    printf("\n--- ECB encrypt single block ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x1 /* ENC */, 0x1 /* ECB */, test_key, zero_iv) != 0) return -1;

    if (wait_for_input_ready() != 0) return -1;
    print_status("  ECB enc ready");

    write_data_in(ecb_pt);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    print_block("Expected", ecb_ct_exp);
    print_block("Got     ", out);
    if (compare_block(out, ecb_ct_exp, "ECB encrypt") != 0) return -1;
    if (check_no_alert("ECB encrypt") != 0) return -1;

    /* Decrypt and verify roundtrip. */
    printf("\n--- ECB decrypt roundtrip ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x2 /* DEC */, 0x1 /* ECB */, test_key, zero_iv) != 0) return -1;

    if (wait_for_input_ready() != 0) return -1;
    print_status("  ECB dec ready");

    write_data_in(ecb_ct_exp);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    print_block("Expected", ecb_pt);
    print_block("Got     ", out);
    if (compare_block(out, ecb_pt, "ECB decrypt roundtrip") != 0) return -1;
    if (check_no_alert("ECB decrypt") != 0) return -1;

    return 0;
}

/* ------------------------------------------------------------------ */
/* CBC 3-Block Encrypt                                                */
/* ------------------------------------------------------------------ */

static int run_cbc_3block(void) {
    uint32_t out[4];

    printf("\n--- CBC 3-block encrypt ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x1 /* ENC */, 0x2 /* CBC */, test_key, cbc_iv) != 0) return -1;

    if (wait_for_input_ready() != 0) return -1;
    print_status("  CBC ready");

    for (int block = 0; block < 3; block++) {
        printf("\n  [Block %d] Writing plaintext\n", block);
        write_data_in(cbc_pt[block]);

        if (wait_for_output_valid() != 0) return -1;
        read_data_out(out);

        print_block("Expected", cbc_ct_exp[block]);
        print_block("Got     ", out);

        if (compare_block(out, cbc_ct_exp[block], "CBC block") != 0) {
            printf("  ERROR: CBC block %d mismatch\n", block);
            return -1;
        }

        if (block < 2) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    if (check_no_alert("CBC encrypt") != 0) return -1;
    return 0;
}

/* ------------------------------------------------------------------ */
/* Main                                                               */
/* ------------------------------------------------------------------ */

int main(void) {
    int rc = 0;

    sep_outbound_filter_init();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_basic_smoke_test (FUNC-001)\n");
    printf("========================================\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);

    /* Part 1: ECB encrypt + decrypt roundtrip */
    if (rc == 0) rc = run_ecb_roundtrip();

    /* Part 2: CBC 3-block encrypt */
    if (rc == 0) rc = run_cbc_3block();

    /* Cleanup */
    cleanup_aes();

    if (rc == 0) {
        printf("\n========================================\n");
        printf("=== sep_aes_basic_smoke_test PASSED ===\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("\n=== sep_aes_basic_smoke_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
