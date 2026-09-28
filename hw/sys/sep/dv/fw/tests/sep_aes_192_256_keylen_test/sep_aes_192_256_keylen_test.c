/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES-192/256 Key Lengths Test (FUNC-003)
 *
 * Coverage:
 *  - AES-192 ECB encrypt with NIST FIPS-197 Appendix C vectors
 *  - AES-256 ECB encrypt with NIST FIPS-197 Appendix C vectors
 *  - AES-192 ECB decrypt roundtrip
 *  - AES-256 ECB decrypt roundtrip
 *  - AES-192 CBC encrypt + decrypt roundtrip (chained mode)
 *  - AES-256 CBC encrypt + decrypt roundtrip (chained mode)
 *  - Alert status monitoring
 */

#include <stdint.h>
#include <stdio.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_aes_init.h"
#include "test_completion.h"
#include "aes_test_util.h"

/* ------------------------------------------------------------------ */
/* Test Vectors                                                       */
/* ------------------------------------------------------------------ */

/* NIST FIPS-197 Appendix C plaintext (shared across key lengths) */
static const uint32_t pt[4] = {
    /* Plaintext = 00112233445566778899aabbccddeeff */
    0x33221100, 0x77665544, 0xbbaa9988, 0xffeeddcc};

/* AES-192 key = 000102030405060708090a0b0c0d0e0f1011121314151617 */
static const uint32_t key_192[6] = {0x03020100, 0x07060504, 0x0b0a0908,
                                    0x0f0e0d0c, 0x13121110, 0x17161514};
static const uint32_t ct_192_exp[4] = {
    /* Ciphertext = dda97ca4864cdfe06eaf70a0ec0d7191 */
    0xa47ca9dd, 0xe0df4c86, 0xa070af6e, 0x91710dec};

/* AES-256 key = 000102...1f */
static const uint32_t key_256[8] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                    0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c};
static const uint32_t ct_256_exp[4] = {
    /* Ciphertext = 8ea2b7ca516745bfeafc49904b496089 */
    0xcab7a28e, 0xbf456751, 0x9049fcea, 0x8960494b};

static const uint32_t zero_iv[4] = {0, 0, 0, 0};

static const uint32_t cbc_iv[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};

/* CBC 3-block plaintext (NIST SP 800-38A) */
static const uint32_t cbc_pt[3][4] = {{0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373},
                                      {0x578a2dae, 0x9cac031e, 0xac6fb79e, 0x518eaf45},
                                      {0x461cc830, 0x11e45ca3, 0x19c1fbe5, 0xef520a1a}};

/* ------------------------------------------------------------------ */
/* ECB Encrypt + Decrypt                                              */
/* ------------------------------------------------------------------ */

static int run_ecb_encrypt(const char *name, uint32_t key_len_onehot, const uint32_t *key_words,
                           int key_words_n, const uint32_t ct_exp[4]) {
    uint32_t out[4];

    printf("\n--- %s ECB encrypt ---\n", name);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x1 /* ENC */, 0x1 /* ECB */, key_len_onehot, key_words, key_words_n,
                           NULL, zero_iv, 0x0) != 0)
        return -1;

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(pt);

    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    print_block("Expected", ct_exp);
    print_block("Got     ", out);
    if (compare_block(out, ct_exp, name) != 0) return -1;
    if (check_no_alert(name) != 0) return -1;

    return 0;
}

static int run_ecb_decrypt(const char *name, uint32_t key_len_onehot, const uint32_t *key_words,
                           int key_words_n, const uint32_t ct_input[4], const uint32_t pt_exp[4]) {
    uint32_t out[4];

    printf("\n--- %s ECB decrypt ---\n", name);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x2 /* DEC */, 0x1 /* ECB */, key_len_onehot, key_words, key_words_n,
                           NULL, zero_iv, 0x0) != 0)
        return -1;

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(ct_input);

    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    print_block("Expected", pt_exp);
    print_block("Got     ", out);
    if (compare_block(out, pt_exp, name) != 0) return -1;
    if (check_no_alert(name) != 0) return -1;

    return 0;
}

/* ------------------------------------------------------------------ */
/* CBC Encrypt + Decrypt Roundtrip (3 blocks)                         */
/* ------------------------------------------------------------------ */

static int run_cbc_roundtrip(const char *name, uint32_t key_len_onehot, const uint32_t *key_words,
                             int key_words_n) {
    uint32_t ct_stored[3][4];
    uint32_t out[4];
    char tag[64];

    /* Encrypt 3 blocks */
    printf("\n--- %s CBC 3-block encrypt ---\n", name);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x1 /* ENC */, 0x2 /* CBC */, key_len_onehot, key_words, key_words_n,
                           NULL, cbc_iv, 0x0) != 0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < 3; block++) {
        write_data_in(cbc_pt[block]);
        if (wait_for_output_valid() != 0) return -1;
        read_data_out(ct_stored[block]);

        snprintf(tag, sizeof(tag), "%s CBC enc block %d", name, block);
        printf("  %s CT: %08x %08x %08x %08x\n", tag, ct_stored[block][0], ct_stored[block][1],
               ct_stored[block][2], ct_stored[block][3]);

        if (block < 2) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    if (check_no_alert(name) != 0) return -1;

    /* Decrypt 3 blocks and verify roundtrip */
    printf("\n--- %s CBC 3-block decrypt roundtrip ---\n", name);

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x2 /* DEC */, 0x2 /* CBC */, key_len_onehot, key_words, key_words_n,
                           NULL, cbc_iv, 0x0) != 0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < 3; block++) {
        write_data_in(ct_stored[block]);
        if (wait_for_output_valid() != 0) return -1;
        read_data_out(out);

        snprintf(tag, sizeof(tag), "%s CBC dec block %d", name, block);
        if (compare_block(out, cbc_pt[block], tag) != 0) return -1;

        if (block < 2) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    printf("  %s CBC roundtrip verified\n", name);
    if (check_no_alert(name) != 0) return -1;

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
    printf("sep_aes_192_256_keylen_test (FUNC-003)\n");
    printf("========================================\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);

    /* ECB encrypt with NIST golden vectors */
    if (rc == 0) rc = run_ecb_encrypt("AES-192", 0x2, key_192, 6, ct_192_exp);
    if (rc == 0) rc = run_ecb_encrypt("AES-256", 0x4, key_256, 8, ct_256_exp);

    /* ECB decrypt roundtrip */
    if (rc == 0) rc = run_ecb_decrypt("AES-192", 0x2, key_192, 6, ct_192_exp, pt);
    if (rc == 0) rc = run_ecb_decrypt("AES-256", 0x4, key_256, 8, ct_256_exp, pt);

    /* CBC encrypt + decrypt roundtrip (chained mode) */
    if (rc == 0) rc = run_cbc_roundtrip("AES-192", 0x2, key_192, 6);
    if (rc == 0) rc = run_cbc_roundtrip("AES-256", 0x4, key_256, 8);

    cleanup_aes();

    if (rc == 0) {
        printf("\n========================================\n");
        printf("=== sep_aes_192_256_keylen_test PASSED ===\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("\n=== sep_aes_192_256_keylen_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
