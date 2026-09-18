/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES MB-Scale Streaming Round-Trip Test (STRESS-003)
 *
 * Companion to STRESS-002 (sep_aes_large_payload_test). STRESS-002 buffers the
 * whole ciphertext in DCCM, so it is capped at 64 KiB (4096 blocks). This test
 * removes that cap by STREAMING the payload in fixed-size chunks: a small
 * pt/ct chunk pair (CHUNK_BLOCKS each) is reused across many chunks, so the
 * total processed payload reaches MB scale while DCCM usage stays ~8 KiB.
 *
 * At the AES masking-PRNG reseed cadence the engine reseeds from
 * real EDN entropy; a sustained MB run exercises the reseed/EDN endurance path
 * and long-run data integrity that a 64 KiB run does not reach.
 *
 * A companion cocotb test injects ONE packed word into COLD_SCRATCH_7:
 *   [31:16] = total_chunks (0 => firmware default DEFAULT_TOTAL_CHUNKS)
 *   [15:0]  = seed (forced non-zero) -> selects key_len and seeds the
 *             deterministic plaintext PRNG.
 *
 * Mode is fixed ECB so each block is independent: an encrypt-then-decrypt
 * round-trip per chunk needs no IV/chain state carried across the ENC<->DEC
 * switch or across chunk boundaries.
 *
 * Verification: per block, decrypt(encrypt(PT)) == PT (byte-exact). A NIST
 * AES-128 ECB golden block runs first to anchor symmetric ENC/DEC correctness
 * (a fault a pure round-trip could mask).
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

/* Reused chunk buffers: 256 blocks * 4 words * 4 bytes = 4 KiB each (8 KiB). */
#ifndef AES_MB_STREAM_CHUNK_BLOCKS
#define AES_MB_STREAM_CHUNK_BLOCKS 256u
#endif
/* Default total chunks: 256 * 256 blocks * 16 B = 1 MiB. */
#ifndef AES_MB_STREAM_DEFAULT_CHUNKS
#define AES_MB_STREAM_DEFAULT_CHUNKS 256u
#endif

#define FW_READY_MAGIC 0xA1E50007u
#define HANDSHAKE_TIMEOUT 2000000

/* CTRL_SHADOWED.OPERATION encodings */
#define AES_OP_ENC 0x1u
#define AES_OP_DEC 0x2u

/* ------------------------------------------------------------------ */
/* Minimal trap handler (no printf -> avoids recursive traps)         */
/* ------------------------------------------------------------------ */
#define STDOUT_ADDR 0x80000000
static void raw_putc(char c) {
    *(volatile uint8_t *)STDOUT_ADDR = (uint8_t)c;
}
static void raw_puts(const char *s) {
    while (*s) raw_putc(*s++);
}
static void raw_hex32(uint32_t v) {
    const char hex[] = "0123456789abcdef";
    raw_puts("0x");
    for (int i = 28; i >= 0; i -= 4) raw_putc(hex[(v >> i) & 0xf]);
}
void trap_dump(uint32_t mcause, uint32_t mepc, uint32_t mtval) __attribute__((noreturn));
void trap_dump(uint32_t mcause, uint32_t mepc, uint32_t mtval) {
    raw_puts("\n*** TRAP ***\nmcause=");
    raw_hex32(mcause);
    raw_puts("\nmepc=");
    raw_hex32(mepc);
    raw_puts("\nmtval=");
    raw_hex32(mtval);
    raw_putc('\n');
    test_fail(1);
    while (1) __asm__ volatile("wfi");
}
static void trap_handler_c(void) __attribute__((naked));
static void trap_handler_c(void) {
    __asm__ volatile("addi  sp, sp, -16   \n"
                     "sw    ra, 12(sp)    \n"
                     "csrr  a0, mcause    \n"
                     "csrr  a1, mepc      \n"
                     "csrr  a2, mtval     \n"
                     "call  trap_dump     \n");
}
static void install_trap_handler(void) {
    uintptr_t addr = (uintptr_t)&trap_handler_c;
    __asm__ volatile("csrw mtvec, %0" ::"r"(addr));
}

/* ------------------------------------------------------------------ */
/* Config tables                                                      */
/* ------------------------------------------------------------------ */
#define AES_MODE_ECB 0x1u
static const uint32_t KEYLENS[3] = {0x1u, 0x2u, 0x4u}; /* 128 192 256 */
static const int KEYWORDS[3] = {4, 6, 8};
static const int KEYBITS[3] = {128, 192, 256};

/* key128 = NIST SP800-38A F.1 key (used by the golden anchor). */
static const uint32_t key128[8] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09, 0, 0, 0, 0};
static const uint32_t key192[8] = {0x10eb3d60, 0xbe71ca15, 0xf0ae732b, 0x81777d85,
                                   0x072c351f, 0xd708613b, 0,          0};
static const uint32_t key256[8] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                   0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c};
static const uint32_t zero_iv[4] = {0, 0, 0, 0};

/* NIST SP800-38A F.1.1 ECB-AES128 block #1 (golden anchor) */
static const uint32_t ecb_pt_base[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};
static const uint32_t ecb_ct_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

/* Reused per-chunk buffers (NOT the whole payload). */
static uint32_t pt_buf[AES_MB_STREAM_CHUNK_BLOCKS * 4];
static uint32_t ct_buf[AES_MB_STREAM_CHUNK_BLOCKS * 4];

/* ------------------------------------------------------------------ */
/* Deterministic plaintext PRNG (xorshift32) - continuous over run     */
/* ------------------------------------------------------------------ */
static uint32_t prng_state;
static void prng_seed(uint32_t s) {
    prng_state = s ? s : 1u;
}
static uint32_t prng_next(void) {
    uint32_t x = prng_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    prng_state = x;
    return x;
}

/* ------------------------------------------------------------------ */
/* Per-block status check: OUTPUT_LOST + alert                        */
/* ------------------------------------------------------------------ */
static int check_block_status(uint32_t block, const char *phase) {
    aes__STATUS_t st = {.w = READ_REG(OCH_SEP_TOP_AES_STATUS_BASE_ADDR)};
    if (st.f.OUTPUT_LOST) {
        printf("  ERROR: OUTPUT_LOST at %s block %u (STATUS=0x%08x)\n", phase, block, st.w);
        return -1;
    }
    if (st.f.STALL) {
        printf("  WARNING: STALL at %s block %u (STATUS=0x%08x)\n", phase, block, st.w);
    }
    return check_no_alert(phase);
}

/* ------------------------------------------------------------------ */
/* One-time public KEY_SHARE read-as-zero probe                        */
/* ------------------------------------------------------------------ */
static int check_key_share_read_zero(void) {
    printf("\n--- Public KEY_SHARE read-as-zero probe ---\n");
    if (wait_for_idle() != 0) return -1;

    for (uint32_t i = 0; i < 8; i++) {
        uint32_t s0_pattern = 0xA5A50000u | (i * 0x0101u) | i;
        uint32_t s1_pattern = 0x5A5A0000u | (i * 0x0101u) | i;
        uint32_t s0_rb;
        uint32_t s1_rb;

        WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(0) + i * 4u, s0_pattern);
        s0_rb = READ_REG(OCH_SEP_TOP_AES_KEY_SHARE0_BASE_ADDR(0) + i * 4u);
        if (s0_rb != 0) {
            printf("  ERROR: KEY_SHARE0_%u read-as-zero violation: wrote=0x%08x read=0x%08x\n", i,
                   s0_pattern, s0_rb);
            return -1;
        }

        WRITE_REG(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(0) + i * 4u, s1_pattern);
        s1_rb = READ_REG(OCH_SEP_TOP_AES_KEY_SHARE1_BASE_ADDR(0) + i * 4u);
        if (s1_rb != 0) {
            printf("  ERROR: KEY_SHARE1_%u read-as-zero violation: wrote=0x%08x read=0x%08x\n", i,
                   s1_pattern, s1_rb);
            return -1;
        }
    }

    printf("  Public KEY_SHARE0/1 read-as-zero PASS\n");
    return 0;
}

/* ------------------------------------------------------------------ */
/* Golden anchor: one NIST AES-128 ECB block                          */
/* ------------------------------------------------------------------ */
static int run_golden_anchor(void) {
    uint32_t out[4];
    printf("\n--- Golden anchor: NIST AES-128 ECB block ---\n");
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(AES_OP_ENC, AES_MODE_ECB, KEYLENS[0], key128, 4, NULL, zero_iv, 0x0) !=
        0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;
    write_data_in(ecb_pt_base);
    if (wait_for_output_valid() != 0) return -1;
    read_data_out(out);
    if (compare_block(out, ecb_ct_exp, "golden ECB-128") != 0) return -1;
    printf("  Golden anchor PASS\n");
    return 0;
}

/* ------------------------------------------------------------------ */
/* cocotb handshake: publish ready, read packed {total_chunks, seed}   */
/* ------------------------------------------------------------------ */
static int get_config(uint16_t *seed_o, uint32_t *chunks_o) {
    WRITE_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7), 0); /* pre-clear */
    WRITE_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6), FW_READY_MAGIC);

    uint32_t word = 0;
    int to = HANDSHAKE_TIMEOUT;
    while (to-- > 0) {
        word = READ_REG(OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7));
        if (word != 0) break;
    }
    if (word == 0) {
        printf("ERROR: cocotb seed handshake timeout\n");
        return -1;
    }

    uint16_t seed = (uint16_t)(word & 0xFFFFu);
    uint32_t chunks = (word >> 16) & 0xFFFFu;
    if (seed == 0) seed = 1u;
    if (chunks == 0) chunks = AES_MB_STREAM_DEFAULT_CHUNKS; /* 0 => default */

    *seed_o = seed;
    *chunks_o = chunks;
    return 0;
}

/* ------------------------------------------------------------------ */
/* Encrypt one chunk: pt_buf -> ct_buf                                 */
/* ------------------------------------------------------------------ */
static int encrypt_chunk(uint32_t key_len, const uint32_t *key, int key_words, uint32_t chunk) {
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(AES_OP_ENC, AES_MODE_ECB, key_len, key, key_words, NULL, zero_iv, 0x0) !=
        0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;
    for (uint32_t b = 0; b < AES_MB_STREAM_CHUNK_BLOCKS; b++) {
        write_data_in(&pt_buf[b * 4]);
        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(chunk, "ENC") != 0) return -1;
        read_data_out(&ct_buf[b * 4]);
        if (b != AES_MB_STREAM_CHUNK_BLOCKS - 1) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Decrypt+verify one chunk: ct_buf -> recovered PT vs pt_buf          */
/* ------------------------------------------------------------------ */
static int decrypt_verify_chunk(uint32_t key_len, const uint32_t *key, int key_words,
                                uint32_t chunk) {
    uint32_t rpt[4];
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(AES_OP_DEC, AES_MODE_ECB, key_len, key, key_words, NULL, zero_iv, 0x0) !=
        0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;
    for (uint32_t b = 0; b < AES_MB_STREAM_CHUNK_BLOCKS; b++) {
        write_data_in(&ct_buf[b * 4]);
        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(chunk, "DEC") != 0) return -1;
        read_data_out(rpt);
        if (compare_block(rpt, &pt_buf[b * 4], "round-trip") != 0) {
            printf("  ERROR: round-trip mismatch chunk %u block %u\n", chunk, b);
            return -1;
        }
        if (b != AES_MB_STREAM_CHUNK_BLOCKS - 1) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Main                                                               */
/* ------------------------------------------------------------------ */
int main(void) {
    int rc = 0;
    uint16_t seed = 0;
    uint32_t chunks = 0;
    uint32_t key_len = 0;
    int key_words = 0, ki = 0;
    const uint32_t *key = key128;

    sep_outbound_filter_init();
    install_trap_handler();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_mb_stream_test (STRESS-003)\n");
    printf("========================================\n");
    printf("AES base=0x%08x  chunk=%u blocks (%u bytes), streaming\n", OCH_SEP_TOP_AES_BASE_ADDR,
           AES_MB_STREAM_CHUNK_BLOCKS, AES_MB_STREAM_CHUNK_BLOCKS * 16u);

    if (rc == 0) rc = check_key_share_read_zero();
    if (rc == 0) rc = run_golden_anchor();
    if (rc == 0) rc = get_config(&seed, &chunks);

    if (rc == 0) {
        ki = (seed >> 8) % 3;
        key_len = KEYLENS[ki];
        key_words = KEYWORDS[ki];
        key = (ki == 0) ? key128 : (ki == 1) ? key192 : key256;
        prng_seed((uint32_t)seed | 1u);
        printf("Config: seed=0x%04x key=%d-bit chunks=%u total=%u bytes (%u blocks)\n", seed,
               KEYBITS[ki], chunks, chunks * AES_MB_STREAM_CHUNK_BLOCKS * 16u,
               chunks * AES_MB_STREAM_CHUNK_BLOCKS);
    }

    for (uint32_t c = 0; rc == 0 && c < chunks; c++) {
        /* Continuous PRNG stream -> fresh plaintext for this chunk. */
        for (uint32_t w = 0; w < AES_MB_STREAM_CHUNK_BLOCKS * 4; w++) pt_buf[w] = prng_next();

        rc = encrypt_chunk(key_len, key, key_words, c);
        if (rc == 0) rc = decrypt_verify_chunk(key_len, key, key_words, c);

        if (rc == 0 && (c % 64u == 63u))
            printf("  progress: %u/%u chunks (%u KiB) OK\n", c + 1u, chunks,
                   (c + 1u) * AES_MB_STREAM_CHUNK_BLOCKS * 16u / 1024u);
    }

    cleanup_aes();

    if (rc == 0) {
        printf("=== sep_aes_mb_stream_test PASSED (%d-bit, %u chunks, %u bytes) ===\n", KEYBITS[ki],
               chunks, chunks * AES_MB_STREAM_CHUNK_BLOCKS * 16u);
        test_pass(0);
    } else {
        printf("=== sep_aes_mb_stream_test FAILED ===\n");
        test_fail(1);
    }

    while (1) __asm__("wfi");
}
