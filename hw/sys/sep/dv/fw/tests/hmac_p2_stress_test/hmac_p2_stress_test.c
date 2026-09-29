/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * HMAC P2 Stress Test - continuous SHA-256 operations without IP reset.
 *
 * Verifies repeated hash_start/hash_process cycles can run back-to-back while
 * sha_en remains asserted. Each iteration clears hmac_done and checks that the
 * next operation retriggers completion and produces an independent digest.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_hmac.h"
#include "test_completion.h"

typedef struct {
    const char *name;
    const uint8_t *data;
    uint32_t len;
    const char *expected_hex;
} hmac_stress_case_t;

static const uint8_t msg_empty[] = "";
static const uint8_t msg_abc[] = "abc";
static const uint8_t msg_hello[] = "Hello OTBN.";
static const uint8_t msg_iter3[] = "continuous-hmac-stress-iteration-3";
static const uint8_t msg_64[64] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
    0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f,
    0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f,
    0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x3b, 0x3c, 0x3d, 0x3e, 0x3f,
};
static uint8_t msg_96[96];

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000ffu) << 24) | ((x & 0x0000ff00u) << 8) | ((x & 0x00ff0000u) >> 8) |
           ((x & 0xff000000u) >> 24);
}

static void init_msg_96(void) {
    for (uint32_t i = 0; i < sizeof(msg_96); i++) {
        msg_96[i] = (uint8_t)((i * 7u + 3u) & 0xffu);
    }
}

static void clear_hmac_done(void) {
    hmac__INTR_STATE_t clear = {.w = 0};
    clear.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
}

static int wait_for_hmac_done(void) {
    int timeout = 1000000;
    while (timeout-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        if (intr.f.hmac_done) {
            return 0;
        }
    }

    printf("  Timeout waiting for hmac_done\n");
    return -1;
}

static int feed_msg(const uint8_t *data, uint32_t len) {
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;

    for (uint32_t i = 0; i < len; i++) {
        int spins = 0;
        hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        while (status.f.fifo_full) {
            if (spins++ > 10000) {
                printf("  FIFO full timeout at byte %u\n", i);
                return -1;
            }
            status.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR);
        }
        *fifo8 = data[i];
    }

    return 0;
}

static void read_digest_hex(char *hex_out) {
    static const char hex_chars[] = "0123456789abcdef";

    for (int word = 0; word < 8; word++) {
        uint32_t raw = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(word));
        uint32_t digest_word = bswap32(raw);
        for (int byte = 0; byte < 4; byte++) {
            uint8_t value = (uint8_t)(digest_word >> (byte * 8));
            int idx = word * 8 + byte * 2;
            hex_out[idx + 0] = hex_chars[(value >> 4) & 0xf];
            hex_out[idx + 1] = hex_chars[value & 0xf];
        }
    }
    hex_out[64] = '\0';
}

static void cleanup_hmac(void) {
    hmac__CFG_t cfg = {.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR)};
    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xffffffffu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
    clear_hmac_done();
}

static int run_stress_case(const hmac_stress_case_t *test_case, uint32_t iter) {
    printf("\n[Iteration %u] %s (%u bytes)\n", iter, test_case->name, test_case->len);

    clear_hmac_done();
    hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
    if (intr.f.hmac_done) {
        printf("  FAIL: hmac_done did not clear before iteration\n");
        return -1;
    }

    hmac__CMD_t start = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, start.w);

    if (feed_msg(test_case->data, test_case->len) != 0) {
        return -1;
    }

    uint64_t expected_bits = (uint64_t)test_case->len * 8ull;
    uint32_t msg_lo = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_LOWER_BASE_ADDR);
    uint32_t msg_hi = READ_REG(SEP_TOP_HMAC_MSG_LENGTH_UPPER_BASE_ADDR);
    uint32_t exp_lo = (uint32_t)(expected_bits & 0xffffffffu);
    uint32_t exp_hi = (uint32_t)(expected_bits >> 32);
    printf("  MSG_LENGTH=%u:%u expected=%u:%u\n", msg_lo, msg_hi, exp_lo, exp_hi);
    if (msg_lo != exp_lo || msg_hi != exp_hi) {
        printf("  FAIL: message length was polluted by a previous operation\n");
        return -1;
    }

    hmac__CMD_t process = {.f.hash_process = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, process.w);

    if (wait_for_hmac_done() != 0) {
        return -1;
    }

    hmac__STATUS_t status = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
    printf("  STATUS=0x%08x idle=%u empty=%u full=%u depth=%u\n", status.w, status.f.hmac_idle,
           status.f.fifo_empty, status.f.fifo_full, status.f.fifo_depth);
    if (!status.f.hmac_idle) {
        printf("  FAIL: HMAC did not return to idle after completion\n");
        return -1;
    }

    char got_hex[65];
    read_digest_hex(got_hex);
    printf("  Digest:   %s\n", got_hex);
    printf("  Expected: %s\n", test_case->expected_hex);

    if (strcmp(got_hex, test_case->expected_hex) != 0) {
        printf("  FAIL: digest mismatch\n");
        return -1;
    }

    clear_hmac_done();
    intr.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR);
    if (intr.f.hmac_done) {
        printf("  FAIL: hmac_done did not clear after iteration\n");
        return -1;
    }

    return 0;
}

int main(void) {
    sep_outbound_filter_init();
    init_msg_96();

    printf("\n========================================\n");
    printf("HMAC P2 Stress Test\n");
    printf("========================================\n");

    hmac__INTR_ENABLE_t intr_en = {.w = 0};
    intr_en.f.hmac_done = 1;
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.sha_en = 1;
    cfg.f.hmac_en = 0;
    cfg.f.digest_size = SEP_HMAC_DIGEST_SIZE_SHA2_256;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    static const hmac_stress_case_t cases[] = {
        {
            "empty",
            msg_empty,
            0,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        {
            "abc",
            msg_abc,
            3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        },
        {
            "Hello OTBN.",
            msg_hello,
            11,
            "2e8bd199adc454937f7f8c68e3366d8a30b486d35359fbbb83625a716eaf2403",
        },
        {
            "iteration-3 string",
            msg_iter3,
            34,
            "5c247ab3f4980307c838b26c90dc880b1216e1bdd366134c90510470f84d76c9",
        },
        {
            "64-byte ramp",
            msg_64,
            sizeof(msg_64),
            "fdeab9acf3710362bd2658cdc9a29e8f9c757fcf9811603a8c447cd1d9151108",
        },
        {
            "96-byte generated pattern",
            msg_96,
            sizeof(msg_96),
            "c9f1a5f79d7bea01a54f4edb41673722f627ee2e82dda324946b63cf4b9b16af",
        },
    };

    int pass = 1;
    for (uint32_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        if (run_stress_case(&cases[i], i) != 0) {
            pass = 0;
            break;
        }
    }

    cleanup_hmac();

    printf("\n========================================\n");
    if (pass) {
        printf("=== HMAC P2 STRESS TEST PASSED ===\n");
        test_pass(0);
    } else {
        printf("=== HMAC P2 STRESS TEST FAILED ===\n");
        test_fail(1);
    }
    printf("========================================\n");

    while (1) {
        __asm__("wfi");
    }

    return pass ? 0 : -1;
}
