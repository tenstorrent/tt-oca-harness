/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC SHA-256 Step-by-step Test (OpenTitan Programmer's Guide aligned)
 *
 * This test exercises the HMAC/SHA-2 peripheral in a staged manner:
 *   1) Connectivity: read/write scratch registers, test INTR_TEST
 *   2) Basic config sequencing: CFG + CMD.hash_start
 *   3) FIFO feed following STATUS.fifo_full/fifo_depth guidance
 *   4) CMD.hash_process, completion via INTR_STATE.hmac_done/STATUS.hmac_idle
 *   5) Read digest and compare with known vectors
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "test_completion.h"
#include "sep.h"
#include "och_sep_common.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"
// Register addresses, bit-field masks and shifts come from sep.h / sep_addr.h.

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000FFu) << 24) | ((x & 0x0000FF00u) << 8) | ((x & 0x00FF0000u) >> 8) |
           ((x & 0xFF000000u) >> 24);
}

static int wait_for_done_or_idle(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) {
            break;
        }
    }
    if (timeout <= 0) {
        printf("Timeout waiting for HMAC completion\n");
        return -1;
    }
    // Clear hmac_done if set
    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.hmac_done) {
        hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
        WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    }
    return 0;
}

static void print_status(const char *tag) {
    hmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    printf("%s STATUS=0x%08x idle=%u empty=%u full=%u depth=%u\n", tag, s.w, s.f.hmac_idle,
           s.f.fifo_empty, s.f.fifo_full, s.f.fifo_depth);
}

static int stage_connectivity(void) {
    printf("[Stage 1] Connectivity checks\n");
    // Read ERR_CODE and STATUS to ensure MMIO works
    uint32_t err = READ_REG(OCH_SEP_TOP_HMAC_ERR_CODE_BASE_ADDR);
    hmac__STATUS_t sts = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    printf("  ERR_CODE=0x%08x STATUS=0x%08x\n", err, sts.w);

    // Exercise INTR_TEST for hmac_done bit
    hmac__INTR_TEST_t intr_test = {.f.hmac_done = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, intr_test.w);

    hmac__INTR_STATE_t intr = {.w = READ_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (!intr.f.hmac_done) {
        printf("  INTR_TEST did not reflect in INTR_STATE\n");
        return -1;
    }
    // Clear it
    hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
    return 0;
}

static int stage_config(void) {
    printf("[Stage 2] Configure HMAC for SHA-256\n");
    // Enable only hmac_done interrupt
    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    // SHA-256, no swaps, SHA enabled, HMAC disabled
    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 0;                                 // HMAC disabled
    cfg.f.sha_en = 1;                                  // SHA enabled
    cfg.f.endian_swap = 0;                             // No endian swap
    cfg.f.digest_swap = 0;                             // No digest swap
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256; // SHA2_256 (value=1)
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    // Start a new hash
    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    print_status("  After hash_start");
    return 0;
}

static int stage_fifo_feed(const uint8_t *data, uint32_t len) {
    printf("[Stage 3] Feed %u bytes into MSG FIFO\n", len);

    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)OCH_SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;

    for (uint32_t i = 0; i < len; i++) {
        hmac__STATUS_t s = {.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        int spins = 0;
        while (s.f.fifo_full) {
            if (spins++ > 10000) {
                printf("  FIFO full timeout\n");
                return -1;
            }
            s.w = READ_REG(OCH_SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo8 = data[i]; // byte write to ensure exact length accounting
    }

    // Verify message length (in bits) matches exactly on both halves
    uint64_t expected_bits = (uint64_t)len * 8ull;
    uint32_t ml = READ_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR);
    uint32_t mu = READ_REG(OCH_SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR);
    uint32_t exp_lo = (uint32_t)(expected_bits & 0xffffffffu);
    uint32_t exp_hi = (uint32_t)(expected_bits >> 32);
    printf("  MSG_LENGTH lower=%u upper=%u (bits) expected=%u:%u\n", ml, mu, exp_lo, exp_hi);
    if (ml != exp_lo || mu != exp_hi) {
        printf("  Message length mismatch: got %u:%u, expected %u:%u\n", ml, mu, exp_lo, exp_hi);
        return -1;
    }
    return 0;
}

static int stage_process_and_read(uint8_t digest[32]) {
    printf("[Stage 4] Process and read digest\n");
    hmac__CMD_t cmd = {.f.hash_process = 1};
    WRITE_REG(OCH_SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);
    if (wait_for_done_or_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        uint32_t raw = READ_REG(OCH_SEP_TOP_HMAC_DIGEST_BASE_ADDR(i));
        uint32_t swapped = bswap32(raw);
        ((uint32_t *)digest)[i] = swapped;
    }

    // Cleanup: disable SHA and wipe
    hmac__CFG_t cfg = {.w = READ_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(OCH_SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(OCH_SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
    return 0;
}

static void to_hex(const uint8_t *in, char *out) {
    static const char *hex = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        out[2 * i + 0] = hex[(in[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[(in[i] >> 0) & 0xF];
    }
    out[64] = '\0';
}

static int run_case(const char *name, const uint8_t *data, uint32_t len, const char *expected_hex) {
    printf("\n=== %s ===\n", name);

    if (stage_connectivity() != 0) return -1;
    if (stage_config() != 0) return -1;
    if (stage_fifo_feed(data, len) != 0) return -1;

    uint8_t digest[32];
    if (stage_process_and_read(digest) != 0) return -1;

    char got[65];
    to_hex(digest, got);
    printf("Digest:   %s\n", got);
    printf("Expected: %s\n", expected_hex);
    return (strcmp(got, expected_hex) == 0) ? 0 : -1;
}

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    printf("HMAC base=0x%08x\n", OCH_SEP_TOP_HMAC_BASE_ADDR);

    // Simple vectors
    const uint8_t empty[] = "";
    const uint8_t abc[] = "abc";
    const uint8_t hello[] = "Hello OTBN.";

    const char *empty_hex = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    const char *abc_hex = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    const char *hello_hex = "2e8bd199adc454937f7f8c68e3366d8a30b486d35359fbbb83625a716eaf2403";

    int pass = 1;
    if (run_case("Empty", empty, 0, empty_hex) != 0) pass = 0;
    if (run_case("abc", abc, 3, abc_hex) != 0) pass = 0;
    if (run_case("Hello OTBN.", hello, 11, hello_hex) != 0) pass = 0;

    if (pass) {
        printf("\n=== Test PASSED ===\n");
        test_pass(0);
    } else {
        printf("FAILED: HMAC SHA-256 test\n");
        test_fail(1);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
