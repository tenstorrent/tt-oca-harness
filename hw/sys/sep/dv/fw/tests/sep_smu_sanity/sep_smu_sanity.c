/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_sanity - SMU-level SEP sanity test.
 *
 * With the real SEP RTL inside the SMU wrapper, shows that the SEP CPU boots
 * from its TCM and reaches HMAC, KMAC and the STDOUT mailbox through the SEP
 * local fabric. HMAC runs a SHA-256 known-answer check. KMAC runs a SHA3-256
 * known-answer check in software entropy mode, so it does not need EDN. The
 * verdict is the test_pass()/test_fail() magic-word handshake on STDOUT.
 */

#include <stdint.h>
#include <string.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/*
 * Each byte store to STDOUT costs the SMU testbench a VPI round trip, so the
 * image reports only 32-bit stage beacons and the magic-word handshake.
 */
#define STAGE_BEACON(stage_id) \
    do { \
        volatile uint32_t *__b = (volatile uint32_t *)(uintptr_t)STDOUT; \
        *__b = 0xB1B0B0B0u | ((uint32_t)(stage_id)&0xFu); \
        __asm__ volatile("fence" ::: "memory"); \
    } while (0)

static inline uint32_t bswap32(uint32_t x) {
    return ((x & 0x000000FFu) << 24) | ((x & 0x0000FF00u) << 8) | ((x & 0x00FF0000u) >> 8) |
           ((x & 0xFF000000u) >> 24);
}

static void to_hex(const uint8_t *in, int n, char *out) {
    static const char *hex = "0123456789abcdef";
    for (int i = 0; i < n; i++) {
        out[2 * i + 0] = hex[(in[i] >> 4) & 0xF];
        out[2 * i + 1] = hex[(in[i] >> 0) & 0xF];
    }
    out[2 * n] = '\0';
}

#define HMAC_TIMEOUT_ITERS 1000000

static int hmac_wait_done_or_idle(void) {
    int t = HMAC_TIMEOUT_ITERS;
    while (t-- > 0) {
        hmac__INTR_STATE_t intr = {.w = READ_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR)};
        hmac__STATUS_t sts = {.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR)};
        if (intr.f.hmac_done || sts.f.hmac_idle) {
            hmac__INTR_STATE_t clear = {.f.hmac_done = 1};
            WRITE_REG(SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, clear.w);
            return 0;
        }
    }
    return -1;
}

static int hmac_sha256_abc(uint8_t digest[32]) {
    hmac__INTR_ENABLE_t intr_en = {.f.hmac_done = 1};
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, intr_en.w);

    hmac__CFG_t cfg = {.w = 0};
    cfg.f.hmac_en = 0;
    cfg.f.sha_en = 1;
    cfg.f.endian_swap = 0;
    cfg.f.digest_swap = 0;
    cfg.f.digest_size = 1; /* SHA2-256 */
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);

    hmac__CMD_t cmd = {.f.hash_start = 1};
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    /* Byte stores keep the hashed message length exact. */
    volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)SEP_TOP_HMAC_MSG_FIFO_BASE_ADDR;
    const char *msg = "abc";
    for (int i = 0; i < 3; i++) {
        int spins = 0;
        hmac__STATUS_t s;
        do {
            s.w = READ_REG(SEP_TOP_HMAC_STATUS_BASE_ADDR);
            if (++spins > 10000) return -1;
        } while (s.f.fifo_full);
        *fifo8 = (uint8_t)msg[i];
    }

    cmd.w = 0;
    cmd.f.hash_process = 1;
    WRITE_REG(SEP_TOP_HMAC_CMD_BASE_ADDR, cmd.w);

    if (hmac_wait_done_or_idle() != 0) return -1;

    for (int i = 0; i < 8; i++) {
        uint32_t raw = READ_REG(SEP_TOP_HMAC_DIGEST_BASE_ADDR(0) + (i * 4));
        ((uint32_t *)digest)[i] = bswap32(raw);
    }

    cfg.w = READ_REG(SEP_TOP_HMAC_CFG_BASE_ADDR);
    cfg.f.sha_en = 0;
    WRITE_REG(SEP_TOP_HMAC_CFG_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_HMAC_WIPE_SECRET_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, 0);
    return 0;
}

static int stage_hmac(void) {
    /* NIST FIPS 180-4 KAT for SHA-256("abc"). */
    static const char *expected_hex =
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

    uint8_t digest[32];
    if (hmac_sha256_abc(digest) != 0) return -1;

    char got[65];
    to_hex(digest, 32, got);
    if (strcmp(got, expected_hex) != 0) return -1;
    return 0;
}

#define KMAC_TIMEOUT_ITERS 1000000

#define KMAC_CMD_START 29
#define KMAC_CMD_PROCESS 46
#define KMAC_CMD_DONE 22

/* NIST SHA3-256("abc") big-endian reference. */
static const uint32_t sha3_256_abc_ref[8] = {0x3a985da7u, 0x4fe225b2u, 0x045c172du, 0x6bd390bdu,
                                             0x855f086eu, 0x3e9d525bu, 0x46bfe245u, 0x11431532u};

static int kmac_wait_idle(void) {
    int t = KMAC_TIMEOUT_ITERS;
    while (t-- > 0) {
        kmac__STATUS_t s = {.w = READ_REG(SEP_TOP_KMAC_STATUS_BASE_ADDR)};
        if (s.f.sha3_idle) return 0;
    }
    return -1;
}

static int kmac_wait_done(void) {
    int t = KMAC_TIMEOUT_ITERS;
    while (t-- > 0) {
        uint32_t intr = READ_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR);
        if (intr & 0x1u) {
            WRITE_REG(SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, 0x1u);
            return 0;
        }
    }
    return -1;
}

static int kmac_sha3_256_abc(uint32_t digest_be[8]) {
    if (kmac_wait_idle() != 0) return -1;

    /* SHA3-256 with software entropy, so EDN is not needed. */
    kmac__CFG_SHADOWED_t cfg = {.w = 0};
    cfg.f.kmac_en = 0;
    cfg.f.mode = 0x0;         /* SHA3 */
    cfg.f.kstrength = 0x2;    /* L256 → SHA3-256 */
    cfg.f.entropy_mode = 0x2; /* SW */
    cfg.f.msg_endianness = 0;
    cfg.f.state_endianness = 0;
    cfg.f.entropy_ready = 0;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);

    /* Software entropy: mark entropy ready, then supply the seed words. */
    cfg.f.entropy_ready = 1;
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    WRITE_REG(SEP_TOP_KMAC_CFG_SHADOWED_BASE_ADDR, cfg.w);
    for (int i = 0; i < 6; i++) {
        WRITE_REG(SEP_TOP_KMAC_ENTROPY_SEED_BASE_ADDR, 0xDEADBEEFu + i);
    }

    kmac__CMD_t cmd = {.w = 0};
    cmd.f.cmd = KMAC_CMD_START;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    /* All three bytes go to one word-aligned address: the fabric width converter
     * drops byte stores that are not word aligned. */
    {
        volatile uint8_t *fifo8 = (volatile uint8_t *)(uintptr_t)(SEP_TOP_KMAC_MSG_FIFO_BASE_ADDR);
        fifo8[0] = 'a';
        fifo8[0] = 'b';
        fifo8[0] = 'c';
    }

    cmd.f.cmd = KMAC_CMD_PROCESS;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);

    if (kmac_wait_done() != 0) return -1;

    /* The digest is the XOR of the two masked state shares. */
    uint32_t share0[8], share1[8];
    for (int i = 0; i < 8; i++) {
        share0[i] = READ_REG(SEP_TOP_KMAC_STATE_BASE_ADDR + (i * 4));
        share1[i] = READ_REG(SEP_TOP_KMAC_STATE_BASE_ADDR + 0x100 + (i * 4));
    }

    /* The state is little-endian; the reference is big-endian. */
    for (int i = 0; i < 8; i++) {
        digest_be[i] = bswap32(share0[i] ^ share1[i]);
    }

    cmd.f.cmd = KMAC_CMD_DONE;
    WRITE_REG(SEP_TOP_KMAC_CMD_BASE_ADDR, cmd.w);
    return 0;
}

static int stage_kmac(void) {
    uint32_t digest_be[8];
    if (kmac_sha3_256_abc(digest_be) != 0) return -1;

    for (int i = 0; i < 8; i++) {
        if (digest_be[i] != sha3_256_abc_ref[i]) return -1;
    }
    return 0;
}

int main(void) {
    /* Open the outbound window before the first STDOUT store: the outbound
     * filter blocks unmatched writes by default, and the resulting store fault
     * kills the image before it can open the window. Beacon 0 therefore means
     * main was entered and the window is open; earlier liveness is covered by
     * sep_smu_boot_health, which needs no outbound path.
     */
    sep_outbound_filter_init();
    STAGE_BEACON(0);
    STAGE_BEACON(1);

    int errors = 0;

    STAGE_BEACON(2);
    if (stage_hmac() != 0) errors++;
    STAGE_BEACON(3);
    if (stage_kmac() != 0) errors++;
    STAGE_BEACON(4);

    if (errors == 0) {
        test_pass(0);
    } else {
        test_fail(errors);
    }

    while (1) {
        __asm__ volatile("wfi");
    }
}
