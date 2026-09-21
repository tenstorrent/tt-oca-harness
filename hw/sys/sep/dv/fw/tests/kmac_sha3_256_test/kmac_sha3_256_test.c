/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SHA-3-256 Known Answer Test
 *
 * Computes SHA-3-256 of "abc" and verifies against NIST known vector.
 * Digest from two STATE shares XORed. Accepts exact, byte-swapped,
 * or non-zero result.
 */

#include <stdint.h>
#include <stdio.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_kmac.h"
#include "kmac_test_vectors.h" // Auto-generated from Python hashlib

static int wait_for_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    printf("Timeout waiting for KMAC idle\n");
    return -1;
}

static int wait_for_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        uint32_t intr = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & KMAC__INTR_STATE__KMAC_DONE_bm) {
            WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm);
            return 0;
        }
    }
    printf("Timeout waiting for KMAC done\n");
    return -1;
}

static void setup_entropy(void) {
    for (int i = 0; i < 6; i++) WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEF + i);
}

static uint32_t byte_swap(uint32_t x) {
    return ((x >> 24) & 0xFFu) | ((x >> 8) & 0xFF00u) | ((x << 8) & 0xFF0000u) |
           ((x << 24) & 0xFF000000u);
}

static int sha3_256_abc_test(void) {
    printf("\n=== SHA-3-256 abc Test ===\n");

    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    cfg.f.msg_endianness = 0;
    cfg.f.state_endianness = 0;
    cfg.f.entropy_ready = 0;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    printf("  CFG: SHA3-256 entropy_mode=SW\n");

    /* In SW mode: set entropy_ready=1 FIRST to enter StSwSeedWait,
     * THEN write ENTROPY_SEED registers. The FSM handshakes each 32-bit
     * seed write via seed_req/seed_ack (seed_update_i pulse per write). */
    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    printf("  entropy_ready set\n");

    setup_entropy();
    printf("  Entropy seed written\n");

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  START issued\n");

    /* Write exactly 3 bytes "abc" using byte stores to the SAME word-aligned
     * base address. prim_packer tracks its own fill position (pos_q) and does
     * not use the TL-UL address — all MSG_FIFO addresses within the 2KB window
     * are equivalent (lower 12 bits ignored by KMAC). Each sb to fifo8[0]
     * generates wmask=4'b0001 (byte lane 0 valid, data[7:0]=value). prim_packer
     * absorbs byte[0] at the current pos_q, then advances pos_q by 8.
     *
     * Byte stores to non-word-aligned addresses (0x10913801, 0x10913802) are
     * dropped by the 64→32 bit AXI DW converter in kmac_wrapper.sv, so ALL three
     * bytes go to the word-aligned fifo8[0]; the address offset within MSG_FIFO
     * is irrelevant because prim_packer's pos_q supplies the byte position.
     */
    {
        volatile uint8_t *fifo8 =
            (volatile uint8_t *)(uintptr_t)(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR);
        fifo8[0] = 'a'; /* sb[0] → wmask=4'b0001, absorbed at pos_q=0  → pos_q=8  */
        fifo8[0] = 'b'; /* sb[0] → wmask=4'b0001, absorbed at pos_q=8  → pos_q=16 */
        fifo8[0] = 'c'; /* sb[0] → wmask=4'b0001, absorbed at pos_q=16 → pos_q=24 */
    }
    printf("  Message abc written (3 bytes via sb[0] x3 to word-aligned base)\n");

    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    printf("  PROCESS issued\n");

    if (wait_for_done() != 0) return -1;
    printf("  Hash complete\n");

    /* Read words 0-11 (SHA-3-256 output + A[3][0] + A[4][0]) */
    uint32_t share0[12], share1[12], digest[8];
    for (int i = 0; i < 12; i++) share0[i] = READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4)));
    for (int i = 0; i < 12; i++)
        share1[i] =
            READ_REG((SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET + (i * 4)));
    for (int i = 0; i < 8; i++) digest[i] = share0[i] ^ share1[i];

    printf("  Share0[0:11]:");
    for (int i = 0; i < 12; i++) printf(" %08x", share0[i]);
    printf("\n  Share1[0:11]:");
    for (int i = 0; i < 12; i++) printf(" %08x", share1[i]);
    printf("\n  Digest[0:7]:");
    for (int i = 0; i < 8; i++) printf(" %08x", digest[i]);
    /* Also show A[4][0] (words 8-9) XOR */
    printf("\n  A[4][0]: %08x %08x  (w8^w8_s1, w9^w9_s1)", share0[8] ^ share1[8],
           share0[9] ^ share1[9]);
    printf("\n  Expected:");
    for (int i = 0; i < 8; i++) printf(" %08x", sha3_256_abc_ref[i]);
    printf("\n");

    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    /* KMAC with state_endianness=0 returns little-endian data.
     * NIST reference is big-endian, so we must byte-swap each word before comparing.
     * If state_endianness=1 was used, no byte-swap would be needed. */
    int pass = 1;
    for (int i = 0; i < 8; i++) {
        uint32_t digest_be = byte_swap(digest[i]); // Convert LE → BE
        if (digest_be != sha3_256_abc_ref[i]) {
            printf("  FAIL: word %d mismatch: got 0x%08x, expected 0x%08x\n", i, digest_be,
                   sha3_256_abc_ref[i]);
            pass = 0;
        }
    }

    if (pass) {
        printf("  PASS: SHA3-256 digest matches NIST reference\n");
        return 0;
    } else {
        printf("  FAIL: digest mismatch\n");
        return -1;
    }
}

static int sha3_256_empty_test(void) {
    printf("\n=== SHA-3-256 empty Test ===\n");
    if (wait_for_idle() != 0) return -1;

    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.mode = SEP_KMAC_MODE_SHA3;
    cfg.f.kstrength = SEP_KMAC_KSTRENGTH_L256;
    cfg.f.entropy_mode = SEP_KMAC_ENTROPY_MODE_SW;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    setup_entropy();

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = SEP_KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    cmd.f.cmd = SEP_KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    if (wait_for_done() != 0) return -1;

    int pass = 1;
    for (int i = 0; i < 8; i++) {
        uint32_t dig = READ_REG(SEP_TOP_KMAC_STATE_BASE_ADDR + (uint32_t)i * 4u) ^
                       READ_REG(SEP_TOP_KMAC_STATE_BASE_ADDR + SEP_KMAC_STATE_SHARE1_OFFSET +
                                (uint32_t)i * 4u);
        uint32_t dig_be = byte_swap(dig);
        if (dig_be != sha3_256_empty_ref[i]) {
            printf("  FAIL: empty DIGEST_%d=0x%08x expected=0x%08x\n", i, dig_be,
                   sha3_256_empty_ref[i]);
            pass = 0;
        }
    }
    cmd.f.cmd = SEP_KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    return pass ? 0 : -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("\n========================================\n");
    printf("  SHA-3-256 Known Answer\n");
    printf("========================================\n");

    int result = 0;
    if (sha3_256_abc_test() != 0) result = -1;
    if (sha3_256_empty_test() != 0) result = -1;

    printf("\n========================================\n");
    if (result == 0) {
        printf("  RESULT: TEST PASSED\n");
        test_pass(0);
    } else {
        printf("  RESULT: TEST FAILED\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }
}
