/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_engine.c
 * @brief T024 - Crypto engine sideload key driver unit test
 *
 * Exercises rom_sideload.h (HMAC, KMAC, AES, OTBN): shred,
 * write key, and dual-share XOR verification for all four engines.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_engine
 */

#include "test_common.h"
#include "rom_sideload.h"
#include "rom_prng.h"
#include "rom_drbg.h"
#include "rom_defs.h"

static rom_km_prng_state_t prng;

typedef struct {
    const char *name;
    uint32_t base;
    uint8_t words_per_share;
    uint8_t key_len;
    void (*shred_fn)(rom_km_prng_state_t *);
    void (*write_fn)(const uint32_t *, uint8_t, rom_km_prng_state_t *);
} engine_desc_t;

static void shred_hmac(rom_km_prng_state_t *p) {
    rom_hmac_shred_key(p, 1);
}
static void shred_kmac(rom_km_prng_state_t *p) {
    rom_kmac_shred_key(p, 1);
}
static void shred_aes(rom_km_prng_state_t *p) {
    rom_aes_shred_key(p, 1);
}
static void shred_otbn(rom_km_prng_state_t *p) {
    rom_otbn_shred_key(p, 1);
}

static void write_hmac(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_hmac_write_key(k, l, p);
}
static void write_kmac(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_kmac_write_key(k, l, p);
}
static void write_aes(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_aes_write_key(k, l, p);
}
static void write_otbn(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_otbn_write_key(k, l, p);
}

static const engine_desc_t engines[] = {
    {"HMAC", KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR, ROM_KM_HMAC_WORDS_PER_SHARE, 8, shred_hmac,
     write_hmac},
    {"KMAC", KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR, ROM_KM_KMAC_WORDS_PER_SHARE, 8, shred_kmac,
     write_kmac},
    {"AES", KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR, ROM_KM_AES_WORDS_PER_SHARE, 8, shred_aes,
     write_aes},
    {"OTBN", KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR, ROM_KM_OTBN_WORDS_PER_SHARE, 12, shred_otbn,
     write_otbn},
};

#define NUM_ENGINES (sizeof(engines) / sizeof(engines[0]))

static uint32_t read_key_ctrl(uint32_t base, uint8_t n) {
    return *(volatile uint32_t *)(base + n * 4u * 2u);
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(300000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(999, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    rom_drbg_init();
    rom_prng_seed(&prng);

    uint32_t e;
    for (e = 0; e < NUM_ENGINES; e++) {
        const engine_desc_t *eng = &engines[e];
        uint8_t N = eng->words_per_share;

        /* Subtest: Shred */
        printf("[%s] Shred...\n", eng->name);
        TEST_SUBTEST_START("Shred");
        rom_prng_seed(&prng);
        eng->shred_fn(&prng);
        {
            uint32_t ctrl = read_key_ctrl(eng->base, N);
            if (ctrl & 1u) {
                TEST_FAIL("%s: KEY_CTRL.key_valid != 0 after shred (ctrl=0x%08X)", eng->name, ctrl);
            }
        }
        TEST_SUBTEST_PASS();

        /* Subtest: Write key */
        printf("[%s] Write key...\n", eng->name);
        TEST_SUBTEST_START("Write key");
        {
            uint32_t key[12];
            uint8_t i;
            for (i = 0; i < eng->key_len; i++) {
                key[i] = 0x01020304u + (uint32_t)i + (e << 16);
            }
            rom_prng_seed(&prng);
            eng->write_fn(key, eng->key_len, &prng);

            uint32_t ctrl = read_key_ctrl(eng->base, N);
            if (!(ctrl & 1u)) {
                TEST_FAIL("%s: KEY_CTRL.key_valid != 1 after write (ctrl=0x%08X)", eng->name, ctrl);
            }
        }
        TEST_SUBTEST_PASS();

        /* Subtest: Verify dual shares via TB readback (SHARE0 ^ SHARE1 == key) */
        printf("[%s] Verify dual shares...\n", eng->name);
        TEST_SUBTEST_START("Verify dual shares");
        {
            uint8_t i;
            for (i = 0; i < eng->key_len; i++) {
                uint32_t s0, s1;
                if (!tb_key_share_read((uint8_t)e, 0, i, &s0)) {
                    TEST_FAIL("%s: tb_key_share_read(share0, word %u) failed", eng->name,
                              (unsigned)i);
                }
                if (!tb_key_share_read((uint8_t)e, 1, i, &s1)) {
                    TEST_FAIL("%s: tb_key_share_read(share1, word %u) failed", eng->name,
                              (unsigned)i);
                }
                uint32_t reconstructed = s0 ^ s1;
                uint32_t expected = 0x01020304u + (uint32_t)i + (e << 16);
                if (reconstructed != expected) {
                    TEST_FAIL("%s: share XOR mismatch at word %u: "
                              "S0=0x%08X S1=0x%08X XOR=0x%08X expected=0x%08X",
                              eng->name, (unsigned)i, s0, s1, reconstructed, expected);
                }
            }
            TEST_LOG("  %s: all %u key words verified via share XOR", eng->name,
                     (unsigned)eng->key_len);
        }
        TEST_SUBTEST_PASS();
    }

    TEST_PASS();
    return 0;
}
