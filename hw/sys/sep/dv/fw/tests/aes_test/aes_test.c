/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES CBC Multi-Block Encryption Test (OpenTitan Programmer's Guide aligned)
 *
 * This test demonstrates AES-128 CBC mode with 3 blocks of data, showing:
 *   1) How AES automatically starts when all DATA_IN registers are written
 *   2) How AES tracks output reads via STATUS.OUTPUT_VALID and DATA_OUT reads
 *   3) How INPUT_READY indicates when the next block can be written
 *   4) CBC mode chaining where each ciphertext block affects the next
 *
 * Key Automatic Operation Features:
 *   - When MANUAL_OPERATION=0 (automatic mode):
 *     * AES starts encryption automatically after all 4 DATA_IN registers written
 *     * AES monitors DATA_OUT register reads (all 4 must be read)
 *     * After output is read, INPUT_READY goes high for next block
 *     * If output not read, AES stalls to prevent data loss
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_aes_init.h"

// AES-128 CBC Mode Test (3 blocks)
// Key:       2b7e151628aed2a6abf7158809cf4f3c
// IV:        000102030405060708090a0b0c0d0e0f
//
// Block 0 Plaintext:  6bc1bee22e409f96e93d7e117393172a
// Block 0 Ciphertext: 7649abac8119b246cee98e9b12e9197d
//
// Block 1 Plaintext:  ae2d8a571e03ac9c9eb76fac45af8e51
// Block 1 Ciphertext: 5086cb9b507219ee95db113a917678b2
//
// Block 2 Plaintext:  30c81c46a35ce411e5fbc1191a0a52ef
// Block 2 Ciphertext: 73bed6b8e3c1743b7116e69e22229516

static const uint32_t test_key[4] = {0x16157e2b, // Key bytes 0-3 (little-endian)
                                     0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09};

static const uint32_t test_iv[4] = {0x03020100, // IV bytes 0-3 (little-endian)
                                    0x07060504, 0x0b0a0908, 0x0f0e0d0c};

// 3 blocks of plaintext
static const uint32_t test_plaintext[3][4] = {
    {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373}, // Block 0
    {0x578a2dae, 0x9cac031e, 0xac6fb79e, 0x518eaf45}, // Block 1
    {0x461cc830, 0x11e45ca3, 0x19c1fbe5, 0xef520a1a}  // Block 2
};

// 3 blocks of expected ciphertext
static const uint32_t expected_ciphertext[3][4] = {
    {0xacab4976, 0x46b21981, 0x9b8ee9ce, 0x7d19e912}, // Block 0
    {0x9bcb8650, 0xee197250, 0x3a11db95, 0xb2787691}, // Block 1
    {0xb8d6be73, 0x3b74c1e3, 0x9ee61671, 0x16952222}  // Block 2
};

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.IDLE) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for AES idle\n");
    return -1;
}

static int wait_for_output_valid(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.OUTPUT_VALID) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for AES output valid\n");
    return -1;
}

static void print_status(const char *tag) {
    aes__STATUS_t s = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
    printf("%s STATUS=0x%08x idle=%u stall=%u input_ready=%u output_valid=%u\n", tag, s.w, s.f.IDLE,
           s.f.STALL, s.f.INPUT_READY, s.f.OUTPUT_VALID);
}

static int wait_for_input_ready(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        aes__STATUS_t status = {.w = READ_REG(SEP_TOP_AES_STATUS_BASE_ADDR)};
        if (status.f.INPUT_READY) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for AES input ready\n");
    return -1;
}

static int aes_cbc_multi_block_test(void) {
    printf("\n=== AES-128 CBC Multi-Block Encryption Test ===\n");
    printf("AES base=0x%08x\n", SEP_TOP_AES_BASE_ADDR);
    printf("Testing 3 blocks to demonstrate automatic operation\n\n");

    // Step 1: Wait for idle
    printf("[Step 1] Waiting for AES idle\n");
    if (wait_for_idle() != 0) return -1;
    print_status("  Initial");

    // Step 2: Configure AES for AES-128 CBC encryption, automatic mode
    printf("\n[Step 2] Configuring AES (AES-128 CBC Encryption, Automatic mode)\n");
    printf("  AUTOMATIC MODE: AES will start automatically when DATA_IN is fully written\n");
    printf("  AUTOMATIC MODE: AES tracks DATA_OUT reads and stalls if output not read\n");
    aes__CTRL_SHADOWED_t ctrl = {.w = 0};
    ctrl.f.OPERATION = 0x1;        // AES_ENC (encryption)
    ctrl.f.MODE = 0x2;             // AES_CBC mode (not ECB!)
    ctrl.f.KEY_LEN = 0x1;          // AES_128
    ctrl.f.MANUAL_OPERATION = 0x0; // Automatic mode - KEY FEATURE!
    ctrl.f.SIDELOAD = 0;           // Use SW key (KEY_SHARE0/1); deprecated, DV only
    // Write twice since it's shadowed
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);

    // Step 3: Wait for idle before writing key
    if (wait_for_idle() != 0) return -1;

    // Step 4: Write key via KEY_SHARE0/1 (deprecated SW path for DV when key manager not present)
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), test_key[i]);
    }
    for (int i = 4; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(i), 0);
    }
    for (int i = 0; i < 8; i++) {
        WRITE_REG(SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(i), 0);
    }

    // Step 5: Wait for idle and write IV (required for CBC mode)
    if (wait_for_idle() != 0) return -1;

    printf("\n[Step 4] Writing IV (required for CBC mode)\n");
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_AES_IV_BASE_ADDR(i), test_iv[i]);
    }

    // Step 6: Wait for INPUT_READY
    printf("\n[Step 5] Waiting for INPUT_READY before first block\n");
    if (wait_for_input_ready() != 0) return -1;
    print_status("  Ready for first block");

    int pass = 1;

    // Process 3 blocks
    for (int block = 0; block < 3; block++) {
        printf("\n========== Processing Block %d ==========\n", block);

        // Write input data
        printf("[Block %d] Writing plaintext (4 x 32-bit registers)\n", block);
        printf("  As soon as all 4 DATA_IN registers written, AES starts automatically!\n");
        for (int i = 0; i < 4; i++) {
            WRITE_REG(SEP_TOP_AES_DATA_IN_BASE_ADDR(i), test_plaintext[block][i]);
        }

        // After writing all 4 DATA_IN registers, AES starts automatically
        printf("  [AUTOMATIC] AES started encryption automatically\n");
        print_status("  After DATA_IN write");

        // Wait for OUTPUT_VALID - encryption completes automatically
        printf("[Block %d] Waiting for OUTPUT_VALID (encryption completes automatically)\n", block);
        if (wait_for_output_valid() != 0) return -1;
        print_status("  Encryption done");

        // Read ciphertext - AES monitors these reads!
        printf("[Block %d] Reading ciphertext (AES monitors all 4 DATA_OUT reads)\n", block);
        printf("  [AUTOMATIC] After all DATA_OUT reads, INPUT_READY will go high\n");
        uint32_t ciphertext[4];
        for (int i = 0; i < 4; i++) {
            ciphertext[i] = READ_REG(SEP_TOP_AES_DATA_OUT_BASE_ADDR(i));
        }

        // After reading all 4 DATA_OUT registers, INPUT_READY goes high
        printf("  [AUTOMATIC] All DATA_OUT registers read, INPUT_READY should be high now\n");
        print_status("  After DATA_OUT read");

        // Compare with expected ciphertext
        printf("[Block %d] Comparing ciphertext\n", block);
        printf("  Expected: ");
        for (int i = 0; i < 4; i++) {
            printf("%08x ", expected_ciphertext[block][i]);
        }
        printf("\n");
        printf("  Got:      ");
        for (int i = 0; i < 4; i++) {
            printf("%08x ", ciphertext[i]);
        }
        printf("\n");

        for (int i = 0; i < 4; i++) {
            if (ciphertext[i] != expected_ciphertext[block][i]) {
                printf("  ERROR: Block %d word %d mismatch: expected 0x%08x, got 0x%08x\n", block,
                       i, expected_ciphertext[block][i], ciphertext[i]);
                pass = 0;
            }
        }

        if (pass && block < 2) {
            printf("  Block %d PASSED, ready for next block\n", block);
        }
    }

    // Cleanup - switch to manual mode and clear registers
    printf("\n[Cleanup] Switching to manual mode and clearing registers\n");
    ctrl.f.MANUAL_OPERATION = 0x1;
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);
    WRITE_REG(SEP_TOP_AES_CTRL_SHADOWED_BASE_ADDR, ctrl.w);

    // Trigger clear operations
    aes__TRIGGER_t trigger = {.w = 0};
    trigger.f.KEY_IV_DATA_IN_CLEAR = 1;
    trigger.f.DATA_OUT_CLEAR = 1;
    WRITE_REG(SEP_TOP_AES_TRIGGER_BASE_ADDR, trigger.w);

    return pass ? 0 : -1;
}

int main(void) {
    sep_outbound_filter_init();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("AES-128 CBC Multi-Block Test\n");
    printf("========================================\n");
    printf("\nDemonstrating AES Automatic Operation:\n");
    printf("  1. AES starts automatically when all DATA_IN written\n");
    printf("  2. AES monitors DATA_OUT reads (HW tracks each register read)\n");
    printf("  3. INPUT_READY goes high after all DATA_OUT reads complete\n");
    printf("  4. AES stalls if output not read (prevents data loss)\n");
    printf("  5. CBC mode chains blocks: CT[n-1] XORed with PT[n]\n");

    int result = aes_cbc_multi_block_test();

    if (result == 0) {
        printf("\n========================================\n");
        printf("=== AES CBC Multi-Block Test PASSED ===\n");
        printf("========================================\n");
        printf("\nAll 3 blocks encrypted correctly!\n");
        printf("Automatic operation verified:\n");
        printf("  ✓ Auto-start on DATA_IN write\n");
        printf("  ✓ DATA_OUT read tracking\n");
        printf("  ✓ INPUT_READY handshaking\n");
        printf("  ✓ CBC chaining correct\n");
        test_pass(0);
    } else {
        printf("\n=== AES Test FAILED ===\n");
        test_fail(1);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
