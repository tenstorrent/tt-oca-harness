/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * KMAC-128 Test (Based on AES test structure)
 *
 * This test demonstrates KMAC-128 operation with a simple message.
 * KMAC (Keccak Message Authentication Code) is a PRF and keyed hash function
 * based on Keccak, standardized in NIST SP 800-185.
 *
 * Test Vector: KMAC128("", "", 256, "KMAC") - empty key, empty message
 * Expected: First test to get hardware working, then add proper test vectors
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"

// Simple test: all zeros for now to verify hardware works
static const uint32_t test_key[8] = {0, 0, 0, 0, 0, 0, 0, 0};

static void print_status(const char *tag) {
    kmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
    printf(
        "%s STATUS=0x%08x idle=%u absorb=%u squeeze=%u fifo_empty=%u fifo_full=%u fifo_depth=%u\n",
        tag, s.w, s.f.SHA3_IDLE, s.f.SHA3_ABSORB, s.f.SHA3_SQUEEZE, s.f.FIFO_EMPTY, s.f.FIFO_FULL,
        s.f.FIFO_DEPTH);
}

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t status = {.w = READ_REG(OCH_SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (status.f.SHA3_IDLE) {
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    uint32_t intr_state;
    while (timeout-- > 0) {
        intr_state = READ_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr_state & 0x1) { // kmac_done interrupt
            // Clear interrupt
            WRITE_REG(OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1);
            return 0;
        }
    }
    printf("ERROR: Timeout waiting for KMAC done\n");
    return -1;
}

static int kmac128_simple_test(void) {
    printf("\n========== KMAC-128 Simple Test ==========\n");
    printf("KMAC base=0x%08x\n", OCH_SEP_TOP_KMAC_BASE_ADDR);

    // Step 1: Wait for idle
    printf("Step 1: Checking idle state...\n");
    if (wait_for_idle() != 0) return -1;
    print_status("  Initial");

    // Step 2: Configure for KMAC-128 BEFORE setting key
    printf("Step 2: Configuring for KMAC-128...\n");
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.KMAC_EN = 1;          // KMAC mode
    cfg.f.MODE = 0x2;           // cSHAKE mode (required for KMAC)
    cfg.f.KSTRENGTH = 0x0;      // L128 (128-bit security strength)
    cfg.f.MSG_ENDIANNESS = 0;   // Little-endian
    cfg.f.STATE_ENDIANNESS = 0; // Little-endian
    cfg.f.ENTROPY_MODE = 0x1;   /* EDN mode = 0x1 (0=None, 1=EDN, 2=SW per hjson) */
    cfg.f.ENTROPY_READY = 0;    // Will set separately
    cfg.f.MSG_MASK = 0;         // No message masking
    cfg.f.SIDELOAD = 0;         // Use SW key (KEY_SHARE0/1); deprecated, DV only

    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w); // Write twice (shadowed)
    printf("  CFG written (entropy_mode=SW)\n");

    // Step 2b: Provide entropy seed for SW mode
    printf("Step 2b: Providing entropy seed...\n");
    // Write ENTROPY_SEED register 6 times (each write loads 32-bit chunk)
    // Using a simple pattern for testing
    for (int i = 0; i < 6; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
    }
    printf("  Entropy seed written (6 x 32-bit chunks)\n");

    // Step 2c: Signal that entropy is ready (required for EnMasking=1)
    printf("Step 2c: Setting entropy_ready...\n");
    cfg.f.ENTROPY_READY = 1; // Signal entropy is ready
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w); // Write twice (shadowed)
    printf("  entropy_ready set\n");

    // Step 3: Set key length (deprecated SW path for DV)
    printf("Step 3: Setting KEY_LEN to Key128...\n");
    kmac__KEY_LEN_t key_len = {.w = 0};
    key_len.f.LEN = 0x0; // Key128
    WRITE_REG(OCH_SEP_TOP_KMAC_KEY_LEN_BASE_ADDR, key_len.w);

    // Step 4: Write key via KEY_SHARE0/1 (deprecated SW path for DV when key manager not present)
    printf("Step 4: Writing key...\n");
    for (int i = 0; i < 4; i++) { // 4 words = 128 bits
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE0_0_BASE_ADDR(i), test_key[i]);
        WRITE_REG(OCH_SEP_TOP_KMAC_KEY_SHARE1_0_BASE_ADDR(i), 0);
    }

    // Step 5: Set PREFIX for KMAC
    printf("Step 5: Setting PREFIX...\n");
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_0_BASE_ADDR(0), 0x4D4B2001); // encode_string("KMAC")
    WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_0_BASE_ADDR(1), 0x00004341);
    for (int i = 2; i < 11; i++) {
        WRITE_REG(OCH_SEP_TOP_KMAC_PREFIX_0_BASE_ADDR(i), 0);
    }

    // Step 6: Issue START
    printf("Step 6: Issuing START...\n");
    kmac__CMD_t cmd = {.w = 0};
    cmd.f.CMD = 29; // CmdStart
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    print_status("  After START");

    // Step 7: Write a simple 4-byte message "test"
    printf("Step 7: Writing message 'test' (4 bytes)...\n");
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR(0), 0x74736574); // "test" in little-endian

    // Step 8: Write right_encode(output_length)
    // For 256-bit output: right_encode(256) = 0x01 0x00 0x02
    //   - 256 in big-endian = 0x0100 (2 bytes)
    //   - Length byte = 0x02
    //   - Result: [byte0=0x01, byte1=0x00, byte2=0x02]
    // In little-endian 32-bit: 0x00020001 (but only 3 bytes used)
    printf("Step 8: Writing right_encode(256)...\n");
    WRITE_REG(OCH_SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR(0), 0x00020001);

    // Step 9: Issue PROCESS
    printf("Step 9: Issuing PROCESS...\n");
    cmd.f.CMD = 46; // CmdProcess
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    print_status("  After PROCESS");

    // Step 10: Wait for completion (kmac_done interrupt)
    printf("Step 10: Waiting for completion...\n");
    if (wait_for_done() != 0) return -1;
    print_status("  Done");

    // Step 11: Read digest
    // Note: With EnMasking=1, STATE has two shares that must be XORed
    // STATE layout: 0x400-0x4C7 = share0, 0x500-0x5C7 = share1
    printf("Step 11: Reading digest (with masking - XORing two shares)...\n");
    uint32_t share0[8], share1[8], digest[8];

    // Read share 0 (first 256 bits / 8 words)
    for (int i = 0; i < 8; i++) {
        share0[i] = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(i * 4));
    }

    // Read share 1 (offset by 256 bytes = 0x100 from share0)
    // According to OpenTitan: "0x500 - 0x5C7: Mask share of the state"
    for (int i = 0; i < 8; i++) {
        share1[i] = READ_REG(OCH_SEP_TOP_KMAC_STATE_BASE_ADDR(0x100 + (i * 4)));
    }

    // XOR shares to get actual digest
    for (int i = 0; i < 8; i++) {
        digest[i] = share0[i] ^ share1[i];
    }

    printf("  Share0: ");
    for (int i = 0; i < 8; i++) {
        printf("%08x ", share0[i]);
    }
    printf("\n");

    printf("  Share1: ");
    for (int i = 0; i < 8; i++) {
        printf("%08x ", share1[i]);
    }
    printf("\n");

    printf("  Digest (XOR): ");
    for (int i = 0; i < 8; i++) {
        printf("%08x ", digest[i]);
    }
    printf("\n");

    // Step 12: Issue DONE
    printf("Step 12: Issuing DONE...\n");
    cmd.f.CMD = 22; // CmdDone
    WRITE_REG(OCH_SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    print_status("  After DONE");

    // Check if we got non-zero digest
    int non_zero = 0;
    for (int i = 0; i < 8; i++) {
        if (digest[i] != 0) non_zero = 1;
    }

    if (non_zero) {
        printf("\n*** KMAC-128 TEST PASSED (got non-zero digest) ***\n");
        return 0;
    } else {
        printf("\n*** KMAC-128 TEST FAILED (digest is all zeros) ***\n");
        return -1;
    }
}

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    printf("\n");
    printf("╔══════════════════════════════════════════╗\n");
    printf("║      KMAC-128 Basic Test                 ║\n");
    printf("╚══════════════════════════════════════════╝\n");
    printf("\n");

    int result = kmac128_simple_test();

    if (result == 0) {
        printf("\n=== TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("\n=== TEST FAILED ===\n");
        test_fail(1);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
