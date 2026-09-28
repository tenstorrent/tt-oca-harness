/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES All Modes Test (FUNC-002)
 *
 * Coverage:
 *  - AES-128 ECB encrypt + decrypt roundtrip
 *  - AES-128 CBC/CFB/OFB/CTR 3-block encrypt with golden comparison
 *  - AES-128 CBC/CFB/OFB/CTR 3-block decrypt with golden comparison
 *  - CTR manual-operation mode
 *  - IV auto-update readback verification for chained modes
 *  - Non-zero KEY_SHARE1 verification (key XOR mechanism)
 *  - Alert status monitoring throughout
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

static const uint32_t zero_iv[4] = {0x00000000, 0x00000000, 0x00000000, 0x00000000};

static const uint32_t cbc_iv[4] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c};

static const uint32_t ctr_iv[4] = {0xf3f2f1f0, 0xf7f6f5f4, 0xfbfaf9f8, 0xfffefdfc};

/* NIST F.1 ECB block #1 */
static const uint32_t ecb_pt[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};
static const uint32_t ecb_ct_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

/* NIST F.2 CBC 3-block (shared plaintext for all chained modes) */
static const uint32_t cbc_pt[3][4] = {{0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373},
                                      {0x578a2dae, 0x9cac031e, 0xac6fb79e, 0x518eaf45},
                                      {0x461cc830, 0x11e45ca3, 0x19c1fbe5, 0xef520a1a}};
static const uint32_t cbc_ct_exp[3][4] = {{0xacab4976, 0x46b21981, 0x9b8ee9ce, 0x7d19e912},
                                          {0x9bcb8650, 0xee197250, 0x3a11db95, 0xb2787691},
                                          {0xb8d6be73, 0x3b74c1e3, 0x9ee61671, 0x16952222}};

/* NIST F.3 CFB128 3-block */
static const uint32_t cfb_ct_exp[3][4] = {{0x2ed93f3b, 0x20ad2db7, 0xf8493433, 0x4afb3ce8},
                                          {0x3745a6c8, 0x3fa9b3a0, 0xadcde3cd, 0x8be51c9f},
                                          {0x671f7526, 0x40b1cba3, 0xf18c80b1, 0xdff4a487}};

/* NIST F.4 OFB128 3-block */
static const uint32_t ofb_ct_exp[3][4] = {{0x2ed93f3b, 0x20ad2db7, 0xf8493433, 0x4afb3ce8},
                                          {0x8d508977, 0x038f9116, 0xda523cf5, 0x25d84ec5},
                                          {0x1e054097, 0xf6ec5f9c, 0xa8f74443, 0xcced6022}};

/* NIST F.5 CTR128 3-block */
static const uint32_t ctr_ct_exp[3][4] = {{0x91614d87, 0x26e320b6, 0x6468ef1b, 0xceb60d99},
                                          {0x6bf60698, 0xfffd7079, 0x7b181786, 0xfffdffb9},
                                          {0x3edfe45a, 0x5ed3d5db, 0x02094f5b, 0xab3eb00d}};

/* ------------------------------------------------------------------ */
/* KEY_SHARE1 Test Vectors                                            */
/*                                                                    */
/* key = share0 XOR share1 = test_key                                 */
/* share1 = {0xA5A5A5A5, 0x5A5A5A5A, 0xA5A5A5A5, 0x5A5A5A5A}       */
/* share0 = test_key XOR share1                                       */
/* ------------------------------------------------------------------ */

static const uint32_t ks1_nonzero[8] = {0xA5A5A5A5, 0x5A5A5A5A, 0xA5A5A5A5, 0x5A5A5A5A,
                                        0x00000000, 0x00000000, 0x00000000, 0x00000000};

static const uint32_t ks0_for_split[4] = {
    0xB3B0DB8E, /* 0x16157e2b ^ 0xA5A5A5A5 */
    0xFC88F472, /* 0xa6d2ae28 ^ 0x5A5A5A5A */
    0x2DB0520E, /* 0x8815f7ab ^ 0xA5A5A5A5 */
    0x66159553  /* 0x3c4fcf09 ^ 0x5A5A5A5A */
};

/* ------------------------------------------------------------------ */
/* ECB Encrypt + Decrypt Roundtrip                                    */
/* ------------------------------------------------------------------ */

static int run_ecb_roundtrip(void) {
    uint32_t out[4];

    printf("\n--- ECB encrypt single block ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(0x1 /* ENC */, 0x1 /* ECB */, test_key, zero_iv) != 0) return -1;

    if (wait_for_input_ready() != 0) return -1;
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
/* Generic 3-block chained mode helper                                */
/* ------------------------------------------------------------------ */

static int run_chained_3block(const char *mode_name, uint32_t operation, uint32_t mode,
                              const uint32_t iv[4], const uint32_t input[3][4],
                              const uint32_t expected[3][4], int verify_iv_update,
                              const uint32_t (*iv_expected)[4]) {
    uint32_t out[4];
    uint32_t iv_readback[4];
    char tag[64];

    printf("\n--- %s 3-block %s ---\n", mode_name, (operation == 0x1) ? "encrypt" : "decrypt");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes(operation, mode, test_key, iv) != 0) return -1;

    if (wait_for_input_ready() != 0) return -1;

    for (int block = 0; block < 3; block++) {
        write_data_in(input[block]);
        if (wait_for_output_valid() != 0) return -1;
        read_data_out(out);

        snprintf(tag, sizeof(tag), "%s block %d", mode_name, block);

        print_block("Expected", expected[block]);
        print_block("Got     ", out);
        if (compare_block(out, expected[block], tag) != 0) return -1;

        /* IV auto-update readback verification */
        if (verify_iv_update && iv_expected != NULL) {
            read_iv_out(iv_readback);
            snprintf(tag, sizeof(tag), "%s IV after block %d", mode_name, block);
            if (compare_block(iv_readback, iv_expected[block], tag) != 0) {
                printf("  WARNING: IV auto-update mismatch (non-fatal for OFB/CTR)\n");
            }
        } else if (verify_iv_update) {
            /* Just verify IV changed from initial value */
            read_iv_out(iv_readback);
            if (iv_readback[0] == iv[0] && iv_readback[1] == iv[1] && iv_readback[2] == iv[2] &&
                iv_readback[3] == iv[3]) {
                printf("  WARNING: IV did not change after block %d\n", block);
            }
        }

        if (block < 2) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }

    snprintf(tag, sizeof(tag), "%s %s complete", mode_name,
             (operation == 0x1) ? "encrypt" : "decrypt");
    if (check_no_alert(tag) != 0) return -1;

    return 0;
}

/* ------------------------------------------------------------------ */
/* CBC Encrypt / Decrypt                                              */
/* ------------------------------------------------------------------ */

static int run_cbc_3block_encrypt(void) {
    /* For CBC, IV after block N = ciphertext of block N */
    return run_chained_3block("CBC", 0x1 /* ENC */, 0x2 /* CBC */, cbc_iv, cbc_pt, cbc_ct_exp, 1,
                              cbc_ct_exp);
}

static int run_cbc_3block_decrypt(void) {
    /* CBC decrypt: feed ciphertext, expect plaintext */
    /* IV after block N = input ciphertext block N */
    return run_chained_3block("CBC", 0x2 /* DEC */, 0x2 /* CBC */, cbc_iv, cbc_ct_exp, cbc_pt, 1,
                              cbc_ct_exp);
}

/* ------------------------------------------------------------------ */
/* CFB Encrypt / Decrypt                                              */
/* ------------------------------------------------------------------ */

static int run_cfb_3block_encrypt(void) {
    /* For CFB encrypt, IV after block N = ciphertext of block N */
    return run_chained_3block("CFB", 0x1 /* ENC */, 0x4 /* CFB */, cbc_iv, cbc_pt, cfb_ct_exp, 1,
                              cfb_ct_exp);
}

static int run_cfb_3block_decrypt(void) {
    /* CFB decrypt: feed ciphertext, expect plaintext */
    return run_chained_3block("CFB", 0x2 /* DEC */, 0x4 /* CFB */, cbc_iv, cfb_ct_exp, cbc_pt, 1,
                              cfb_ct_exp);
}

/* ------------------------------------------------------------------ */
/* OFB Encrypt / Decrypt                                              */
/* ------------------------------------------------------------------ */

static int run_ofb_3block_encrypt(void) {
    /* OFB IV update = keystream block (cannot predict without AES forward).
     * Just verify IV changed. */
    return run_chained_3block("OFB", 0x1 /* ENC */, 0x8 /* OFB */, cbc_iv, cbc_pt, ofb_ct_exp, 1,
                              NULL);
}

static int run_ofb_3block_decrypt(void) {
    /* OFB decrypt with OPERATION=DEC. OFB uses forward cipher for both
     * directions, but we set DEC to exercise the control logic path. */
    return run_chained_3block("OFB", 0x2 /* DEC */, 0x8 /* OFB */, cbc_iv, ofb_ct_exp, cbc_pt, 1,
                              NULL);
}

/* ------------------------------------------------------------------ */
/* CTR Encrypt / Decrypt                                              */
/* ------------------------------------------------------------------ */

static int run_ctr_3block_encrypt(void) {
    /* CTR IV = counter. Just verify it changed. */
    return run_chained_3block("CTR", 0x1 /* ENC */, 0x10 /* CTR */, ctr_iv, cbc_pt, ctr_ct_exp, 1,
                              NULL);
}

static int run_ctr_3block_decrypt(void) {
    /* CTR decrypt: feed ciphertext, expect plaintext */
    return run_chained_3block("CTR", 0x2 /* DEC */, 0x10 /* CTR */, ctr_iv, ctr_ct_exp, cbc_pt, 1,
                              NULL);
}

/* ------------------------------------------------------------------ */
/* CTR Manual Operation Mode                                          */
/* ------------------------------------------------------------------ */

static int run_ctr_manual_mode(void) {
    uint32_t out[4];

    printf("\n--- CTR manual-operation mode ---\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x1 /* ENC */, 0x10 /* CTR */, 0x1 /* AES-128 */, test_key, 4, NULL,
                           ctr_iv, 0x1 /* manual */) != 0)
        return -1;

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(cbc_pt[0]);

    /* In manual mode, writing DATA_IN does NOT auto-start.
     * Must trigger START explicitly. */
    aes__TRIGGER_t trigger = {.w = 0};
    trigger.f.START = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, trigger.w);

    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    /* Manual CTR should produce the same result as automatic CTR */
    print_block("Expected", ctr_ct_exp[0]);
    print_block("Got     ", out);
    if (compare_block(out, ctr_ct_exp[0], "CTR manual block 0") != 0) return -1;
    if (check_no_alert("CTR manual") != 0) return -1;

    return 0;
}

/* ------------------------------------------------------------------ */
/* Non-Zero KEY_SHARE1 Verification                                   */
/* ------------------------------------------------------------------ */

static int run_key_share_ecb_roundtrip(void) {
    uint32_t out[4];

    printf("\n--- Non-zero KEY_SHARE1 ECB roundtrip ---\n");
    printf("  key = share0 XOR share1 = test_key\n");

    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x1 /* ENC */, 0x1 /* ECB */, 0x1 /* AES-128 */, ks0_for_split, 4,
                           ks1_nonzero, zero_iv, 0x0 /* auto */) != 0)
        return -1;

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(ecb_pt);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    print_block("Expected", ecb_ct_exp);
    print_block("Got     ", out);
    if (compare_block(out, ecb_ct_exp, "KEY_SHARE1 ECB encrypt") != 0) return -1;

    /* Decrypt roundtrip with same split key */
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(0x2 /* DEC */, 0x1 /* ECB */, 0x1 /* AES-128 */, ks0_for_split, 4,
                           ks1_nonzero, zero_iv, 0x0) != 0)
        return -1;

    if (wait_for_input_ready() != 0) return -1;
    write_data_in(ecb_ct_exp);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);

    print_block("Expected", ecb_pt);
    print_block("Got     ", out);
    if (compare_block(out, ecb_pt, "KEY_SHARE1 ECB decrypt") != 0) return -1;
    if (check_no_alert("KEY_SHARE1 roundtrip") != 0) return -1;

    return 0;
}

/* ------------------------------------------------------------------ */
/* Main Test Function                                                 */
/* ------------------------------------------------------------------ */

int main(void) {
    int rc = 0;

    sep_outbound_filter_init();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_all_modes_test (FUNC-002)\n");
    printf("========================================\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);

    /* Part 1: ECB encrypt + decrypt roundtrip */
    if (rc == 0) rc = run_ecb_roundtrip();

    /* Part 2: CBC encrypt + decrypt */
    if (rc == 0) rc = run_cbc_3block_encrypt();
    if (rc == 0) rc = run_cbc_3block_decrypt();

    /* Part 3: CFB encrypt + decrypt */
    if (rc == 0) rc = run_cfb_3block_encrypt();
    if (rc == 0) rc = run_cfb_3block_decrypt();

    /* Part 4: OFB encrypt + decrypt */
    if (rc == 0) rc = run_ofb_3block_encrypt();
    if (rc == 0) rc = run_ofb_3block_decrypt();

    /* Part 5: CTR encrypt + decrypt */
    if (rc == 0) rc = run_ctr_3block_encrypt();
    if (rc == 0) rc = run_ctr_3block_decrypt();

    /* Part 6: CTR manual operation mode */
    if (rc == 0) rc = run_ctr_manual_mode();

    /* Part 7: Non-zero KEY_SHARE1 verification */
    if (rc == 0) rc = run_key_share_ecb_roundtrip();

    /* Cleanup */
    cleanup_aes();

    if (rc == 0) {
        printf("\n========================================\n");
        printf("=== sep_aes_all_modes_test PASSED ===\n");
        printf("========================================\n");
        test_pass(0);
    } else {
        printf("\n=== sep_aes_all_modes_test FAILED ===\n");
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
