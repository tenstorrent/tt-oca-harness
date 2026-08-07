/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_engine.c
 * @brief T024 - Crypto engine sideload key driver unit test
 *
 * Exercises rom_sideload.h for all sideload engines: shred, write key, and
 * dual-share XOR verification for HMAC, KMAC, AES, OTBN, and the four Adams
 * Bridge seed inputs (MLDSA_SEED, MLKEM_SEED_D, MLKEM_SEED_Z, MLKEM_MSG).
 * Also exercises the ML-KEM shared-key read/consume interface and the
 * handover sideload-key teardown (rom_handover_shred_sideload_keys), which
 * must shred every engine including the ABR seeds and zeroize the shared key.
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_engine
 */

#include "test_common.h"
#include "rom_sideload.h"
#include "rom_handover.h"
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
static void shred_abr_mldsa_seed(rom_km_prng_state_t *p) {
    rom_abr_mldsa_seed_shred_key(p, 1);
}
static void shred_abr_mlkem_seed_d(rom_km_prng_state_t *p) {
    rom_abr_mlkem_seed_d_shred_key(p, 1);
}
static void shred_abr_mlkem_seed_z(rom_km_prng_state_t *p) {
    rom_abr_mlkem_seed_z_shred_key(p, 1);
}
static void shred_abr_mlkem_msg(rom_km_prng_state_t *p) {
    rom_abr_mlkem_msg_shred_key(p, 1);
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
static void write_abr_mldsa_seed(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_abr_mldsa_seed_write_key(k, l, p);
}
static void write_abr_mlkem_seed_d(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_abr_mlkem_seed_d_write_key(k, l, p);
}
static void write_abr_mlkem_seed_z(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_abr_mlkem_seed_z_write_key(k, l, p);
}
static void write_abr_mlkem_msg(const uint32_t *k, uint8_t l, rom_km_prng_state_t *p) {
    rom_abr_mlkem_msg_write_key(k, l, p);
}

/* TB_CMD_KEY_SHARE_READ engine indices:
 *   0=HMAC, 1=KMAC, 2=AES, 3=OTBN, 4=ABR_MLDSA_SEED, 5=ABR_MLKEM_SEED_D,
 *   6=ABR_MLKEM_SEED_Z, 7=ABR_MLKEM_MSG — must match the order in engines[]. */
static const engine_desc_t engines[] = {
    {"HMAC", KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR, ROM_KM_HMAC_WORDS_PER_SHARE, 8, shred_hmac,
     write_hmac},
    {"KMAC", KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR, ROM_KM_KMAC_WORDS_PER_SHARE, 8, shred_kmac,
     write_kmac},
    {"AES", KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR, ROM_KM_AES_WORDS_PER_SHARE, 8, shred_aes,
     write_aes},
    {"OTBN", KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR, ROM_KM_OTBN_WORDS_PER_SHARE, 12, shred_otbn,
     write_otbn},
    {"ABR MLDSA_SEED", KEY_MANAGER_ABR_WRAPPER_KEY_MLDSA_SEED_BASE_ADDR, ROM_KM_ABR_WORDS_PER_SHARE,
     8, shred_abr_mldsa_seed, write_abr_mldsa_seed},
    {"ABR MLKEM_SEED_D", KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_D_BASE_ADDR,
     ROM_KM_ABR_WORDS_PER_SHARE, 8, shred_abr_mlkem_seed_d, write_abr_mlkem_seed_d},
    {"ABR MLKEM_SEED_Z", KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_Z_BASE_ADDR,
     ROM_KM_ABR_WORDS_PER_SHARE, 8, shred_abr_mlkem_seed_z, write_abr_mlkem_seed_z},
    {"ABR MLKEM_MSG", KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_MSG_BASE_ADDR, ROM_KM_ABR_WORDS_PER_SHARE,
     8, shred_abr_mlkem_msg, write_abr_mlkem_msg},
};

#define NUM_ENGINES (sizeof(engines) / sizeof(engines[0]))

static uint32_t read_key_ctrl(uint32_t base, uint8_t n) {
    return *(volatile uint32_t *)(base + n * 4u * 2u);
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(800000)) {
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

    /* ==================================================================
     * Adams Bridge ML-KEM shared-key sub-block
     *
     *   1. TB loads a known pattern into the shared-key sub-block.
     *   2. Read it back through rom_abr_mlkem_sharedkey_read().
     *   3. Verify the read key matches the known pattern.
     *   4. Verify KEY_CTRL.KEY_VALID is now 0 after the read.
     *   5. Verify all KEY words read as 0 (zeroized via hwclr).
     * ================================================================== */
    printf("\n--- Adams Bridge ML-KEM Shared-Key Sub-block Test ---\n");
    TEST_SUBTEST_START("ABR MLKEM Shared-Key Load and Read");

    {
        uint8_t wi;
        for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
            uint32_t word_val = 0xC0FFEE00u | wi;
            if (!tb_drbg_set_next_value(word_val, 1000)) {
                TEST_FAIL("ABR SK: tb_drbg_set_next_value failed for word %u", (unsigned)wi);
            }
            if (!tb_abr_sk_load_word(wi, 1000)) {
                TEST_FAIL("ABR SK: tb_abr_sk_load_word(%u) failed", (unsigned)wi);
            }
        }
        /* Pulse hwset to set KEY_VALID */
        if (!tb_abr_sk_assert_valid(1000)) {
            TEST_FAIL("ABR SK: tb_abr_sk_assert_valid failed");
        }
    }

    uint32_t sk_out[ROM_KM_ABR_WORDS_PER_SHARE];
    rom_abr_mlkem_sharedkey_read(sk_out);

    {
        uint8_t wi;
        for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
            uint32_t expected = 0xC0FFEE00u | wi;
            if (sk_out[wi] != expected) {
                TEST_FAIL("ABR SK: word[%u] mismatch: got=0x%08X expected=0x%08X", (unsigned)wi,
                          sk_out[wi], expected);
            }
        }
        TEST_LOG("  All 8 shared-key words read correctly");
    }

    /* KEY_VALID should be 0 after read (wzc via KEY_CTRL=0) */
    {
        if (ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid) {
            TEST_FAIL("ABR SK: KEY_CTRL.KEY_VALID != 0 after rom_abr_mlkem_sharedkey_read "
                      "(ctrl=0x%08X)",
                      (unsigned)ROM_ABR_MLKEM_SK_CTRL_REG.w);
        }
        TEST_LOG("  KEY_CTRL.KEY_VALID correctly cleared after read");
    }

    /* KEY words should be zeroized (hwclr driven when valid drops) */
    {
        volatile uint32_t *key_regs =
            (volatile uint32_t *)(uintptr_t)KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_BASE_ADDR;
        uint8_t wi;
        for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
            uint32_t v = key_regs[wi];
            if (v != 0u) {
                TEST_FAIL("ABR SK: KEY[%u] not zeroized after clear (got=0x%08X)", (unsigned)wi, v);
            }
        }
        TEST_LOG("  All KEY[*] zeroized after consume");
    }

    TEST_SUBTEST_PASS();

    /* ==================================================================
     * Handover sideload-key teardown test
     *
     * rom_handover_shred_sideload_keys() must clear every crypto-engine
     * sideload key (HMAC/KMAC/AES/OTBN + 4 ABR seeds) and zeroize the ML-KEM
     * shared key, so mutable firmware inherits no ROM-sideloaded material.
     * ================================================================== */
    printf("\n--- Handover Sideload-Key Teardown Test ---\n");

    /* Re-arm every dual-share engine with a fresh known key (sets key_valid). */
    for (e = 0; e < NUM_ENGINES; e++) {
        const engine_desc_t *eng = &engines[e];
        uint32_t key[12];
        uint8_t i;
        for (i = 0; i < eng->key_len; i++) {
            key[i] = 0x0A0B0C0Du + (uint32_t)i + (e << 16);
        }
        rom_prng_seed(&prng);
        eng->write_fn(key, eng->key_len, &prng);
    }

    /* Load + validate a shared key so the zeroize path has work to do. */
    {
        uint8_t wi;
        for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
            if (!tb_drbg_set_next_value(0x5EED0000u | wi, 1000)) {
                TEST_FAIL("handover: tb_drbg_set_next_value failed (word %u)", (unsigned)wi);
            }
            if (!tb_abr_sk_load_word(wi, 1000)) {
                TEST_FAIL("handover: tb_abr_sk_load_word(%u) failed", (unsigned)wi);
            }
        }
        if (!tb_abr_sk_assert_valid(1000)) {
            TEST_FAIL("handover: tb_abr_sk_assert_valid failed");
        }
    }

    /* Sanity: everything must be valid before the teardown runs. */
    TEST_SUBTEST_START("Pre-handover keys valid");
    {
        for (e = 0; e < NUM_ENGINES; e++) {
            if (!(read_key_ctrl(engines[e].base, engines[e].words_per_share) & 1u)) {
                TEST_FAIL("%s: key_valid != 1 before handover shred", engines[e].name);
            }
        }
        if (!ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid) {
            TEST_FAIL("shared key KEY_VALID != 1 before handover shred");
        }
    }
    TEST_SUBTEST_PASS();

    /* Action under test. */
    rom_prng_seed(&prng);
    rom_handover_shred_sideload_keys();

    /* Every engine key_valid must be cleared. */
    TEST_SUBTEST_START("Handover clears all engine key_valid");
    {
        for (e = 0; e < NUM_ENGINES; e++) {
            uint32_t ctrl = read_key_ctrl(engines[e].base, engines[e].words_per_share);
            if (ctrl & 1u) {
                TEST_FAIL("%s: key_valid != 0 after handover shred (ctrl=0x%08X)", engines[e].name,
                          ctrl);
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* ABR seed shares must be overwritten (no longer reconstruct the key).
     * Engine indices 4..7 are the four ABR seeds. */
    TEST_SUBTEST_START("Handover shreds ABR seed shares");
    {
        for (e = 4; e < NUM_ENGINES; e++) {
            const engine_desc_t *eng = &engines[e];
            uint8_t matches = 0;
            uint8_t i;
            for (i = 0; i < eng->key_len; i++) {
                uint32_t s0, s1;
                if (!tb_key_share_read((uint8_t)e, 0, i, &s0) ||
                    !tb_key_share_read((uint8_t)e, 1, i, &s1)) {
                    TEST_FAIL("%s: tb_key_share_read failed (word %u)", eng->name, (unsigned)i);
                }
                uint32_t original = 0x0A0B0C0Du + (uint32_t)i + (e << 16);
                if ((s0 ^ s1) == original) {
                    matches++;
                }
            }
            if (matches == eng->key_len) {
                TEST_FAIL("%s: shares still reconstruct original key after shred", eng->name);
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* Shared key must be invalidated and zeroized. */
    TEST_SUBTEST_START("Handover zeroizes ML-KEM shared key");
    {
        if (ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid) {
            TEST_FAIL("shared key KEY_VALID != 0 after handover shred (ctrl=0x%08X)",
                      (unsigned)ROM_ABR_MLKEM_SK_CTRL_REG.w);
        }
        volatile uint32_t *key_regs =
            (volatile uint32_t *)(uintptr_t)KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_BASE_ADDR;
        uint8_t wi;
        for (wi = 0; wi < ROM_KM_ABR_WORDS_PER_SHARE; wi++) {
            if (key_regs[wi] != 0u) {
                TEST_FAIL("shared key KEY[%u] not zeroized after handover (got=0x%08X)",
                          (unsigned)wi, key_regs[wi]);
            }
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
