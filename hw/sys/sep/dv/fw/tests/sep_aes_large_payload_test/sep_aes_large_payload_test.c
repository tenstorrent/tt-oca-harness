/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * AES Large-Payload Random-Mode Test (STRESS-002)
 *
 * A companion cocotb test injects ONE packed word into COLD_SCRATCH_7:
 *   [31:16] = block_count (actual blocks this run; 0 or >ceiling => ceiling)
 *   [15:0]  = seed (forced non-zero) -> selects mode/key_len and seeds the
 *             deterministic plaintext PRNG.
 *
 * Verification: encrypt the whole payload into a DCCM ciphertext buffer,
 * then decrypt it back and compare byte-exact against the PRNG-regenerated
 * plaintext. A fixed NIST AES-128 ECB golden block runs first to anchor
 * correctness (catches symmetric ENC/DEC faults a pure round-trip could mask).
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

#ifndef AES_LARGE_PAYLOAD_MAX_BLOCKS
#define AES_LARGE_PAYLOAD_MAX_BLOCKS 4096u /* 64 KiB ceiling in DCCM (128 KiB total) */
#endif

#define FW_READY_MAGIC 0xA1E50006u
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
static const uint32_t MODES[5] = {0x1u, 0x2u, 0x4u, 0x8u, 0x10u}; /* ECB CBC CFB OFB CTR */
static const char *MODE_NAME[5] = {"ECB", "CBC", "CFB", "OFB", "CTR"};
static const uint32_t KEYLENS[3] = {0x1u, 0x2u, 0x4u}; /* 128 192 256 */
static const int KEYWORDS[3] = {4, 6, 8};
static const int KEYBITS[3] = {128, 192, 256};

/* Keys. key128 must be the NIST SP800-38A F.1 key (used by the golden anchor).
 * key192/key256 are arbitrary constants (round-trip is self-consistent). */
static const uint32_t key128[8] = {0x16157e2b, 0xa6d2ae28, 0x8815f7ab, 0x3c4fcf09, 0, 0, 0, 0};
static const uint32_t key192[8] = {0x10eb3d60, 0xbe71ca15, 0xf0ae732b, 0x81777d85,
                                   0x072c351f, 0xd708613b, 0,          0};
static const uint32_t key256[8] = {0x03020100, 0x07060504, 0x0b0a0908, 0x0f0e0d0c,
                                   0x13121110, 0x17161514, 0x1b1a1918, 0x1f1e1d1c};
static const uint32_t base_iv[4] = {0xf3f2f1f0, 0xf7f6f5f4, 0xfbfaf9f8, 0xfffefdfc};
static const uint32_t zero_iv[4] = {0, 0, 0, 0};

/* NIST SP800-38A F.1.1 ECB-AES128 block #1 (golden anchor) */
static const uint32_t ecb_pt_base[4] = {0xe2bec16b, 0x969f402e, 0x117e3de9, 0x2a179373};
static const uint32_t ecb_ct_exp[4] = {0xb47bd73a, 0x60367a0d, 0xf3ca9ea8, 0x97ef6624};

/* Ciphertext buffer in DCCM: ceiling blocks * 4 words. 4096*4*4 = 64 KiB. */
static uint32_t ct_buf[AES_LARGE_PAYLOAD_MAX_BLOCKS * 4];

/* ------------------------------------------------------------------ */
/* Deterministic plaintext PRNG (xorshift32) - software, no RNG IP     */
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
static void gen_pt_block(uint32_t pt[4]) {
    for (int i = 0; i < 4; i++) pt[i] = prng_next();
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
/* Golden anchor: one NIST AES-128 ECB block                          */
/* ------------------------------------------------------------------ */
static int run_golden_anchor(void) {
    uint32_t out[4];
    printf("\n--- Golden anchor: NIST AES-128 ECB block ---\n");
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(AES_OP_ENC, MODES[0], KEYLENS[0], key128, 4, NULL, zero_iv, 0x0) != 0)
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
/* cocotb handshake: publish ready, read packed {block_count, seed}    */
/* ------------------------------------------------------------------ */
static int get_config(uint16_t *seed_o, uint32_t *blocks_o) {
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
    uint32_t blocks = (word >> 16) & 0xFFFFu;
    if (seed == 0) seed = 1u;
    if (blocks == 0 || blocks > AES_LARGE_PAYLOAD_MAX_BLOCKS)
        blocks = AES_LARGE_PAYLOAD_MAX_BLOCKS; /* 0/overflow => ceiling */

    *seed_o = seed;
    *blocks_o = blocks;
    return 0;
}

/* ------------------------------------------------------------------ */
/* Encrypt pass: stream PRNG plaintext -> ct_buf                       */
/* ------------------------------------------------------------------ */
static int encrypt_pass(uint16_t seed, uint32_t blocks, uint32_t mode, uint32_t key_len,
                        const uint32_t *key, int key_words) {
    uint32_t pt[4];
    prng_seed((uint32_t)seed | 1u);
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(AES_OP_ENC, mode, key_len, key, key_words, NULL, base_iv, 0x0) != 0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;
    for (uint32_t b = 0; b < blocks; b++) {
        gen_pt_block(pt);
        write_data_in(pt);
        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(b, "ENC") != 0) return -1;
        read_data_out(&ct_buf[b * 4]);
        if (b != blocks - 1) {
            if (wait_for_input_ready() != 0) return -1;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* Decrypt+verify pass: ct_buf -> recovered PT vs regenerated PT       */
/* ------------------------------------------------------------------ */
static int decrypt_verify_pass(uint16_t seed, uint32_t blocks, uint32_t mode, uint32_t key_len,
                               const uint32_t *key, int key_words) {
    uint32_t rpt[4], pt[4];
    prng_seed((uint32_t)seed | 1u); /* regenerate identical plaintext */
    if (wait_for_idle() != 0) return -1;
    if (configure_aes_full(AES_OP_DEC, mode, key_len, key, key_words, NULL, base_iv, 0x0) != 0)
        return -1;
    if (wait_for_input_ready() != 0) return -1;
    for (uint32_t b = 0; b < blocks; b++) {
        write_data_in(&ct_buf[b * 4]);
        if (wait_for_output_valid() != 0) return -1;
        if (check_block_status(b, "DEC") != 0) return -1;
        read_data_out(rpt);
        gen_pt_block(pt);
        if (compare_block(rpt, pt, "round-trip") != 0) {
            printf("  ERROR: round-trip mismatch at block %u\n", b);
            return -1;
        }
        if (b != blocks - 1) {
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
    uint32_t blocks = 0;
    uint32_t mode = 0, key_len = 0;
    int key_words = 0, mi = 0, ki = 0;
    const uint32_t *key = key128;

    sep_outbound_filter_init();
    install_trap_handler();

    if (sep_aes_sw_reset_release() != 0) {
        test_fail(1);
        while (1) __asm__("wfi");
    }

    printf("\n========================================\n");
    printf("sep_aes_large_payload_test (STRESS-002)\n");
    printf("========================================\n");
    printf("AES base=0x%08x  ceiling=%u blocks (%u bytes)\n", OCH_SEP_TOP_AES_BASE_ADDR,
           AES_LARGE_PAYLOAD_MAX_BLOCKS, AES_LARGE_PAYLOAD_MAX_BLOCKS * 16u);

    if (rc == 0) rc = run_golden_anchor();
    if (rc == 0) rc = get_config(&seed, &blocks);

    if (rc == 0) {
        mi = seed % 5;
        ki = (seed >> 8) % 3;
        mode = MODES[mi];
        key_len = KEYLENS[ki];
        key_words = KEYWORDS[ki];
        key = (ki == 0) ? key128 : (ki == 1) ? key192 : key256;
        printf("Config: seed=0x%04x mode=%s key=%d-bit blocks=%u (%u bytes)\n", seed, MODE_NAME[mi],
               KEYBITS[ki], blocks, blocks * 16u);
    }

    if (rc == 0) rc = encrypt_pass(seed, blocks, mode, key_len, key, key_words);
    if (rc == 0) rc = decrypt_verify_pass(seed, blocks, mode, key_len, key, key_words);

    cleanup_aes();

    if (rc == 0) {
        printf("=== sep_aes_large_payload_test PASSED (%s %d-bit, %u blocks) ===\n", MODE_NAME[mi],
               KEYBITS[ki], blocks);
        test_pass(0);
    } else {
        printf("=== sep_aes_large_payload_test FAILED ===\n");
        test_fail(1);
    }

    while (1) __asm__("wfi");
}
