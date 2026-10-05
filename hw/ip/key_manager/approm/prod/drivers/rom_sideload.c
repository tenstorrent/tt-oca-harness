/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_sideload.c
 * @brief Crypto-engine sideload key driver
 *
 * Implements key_valid clear/set, shred_key, and write_key for all KM
 * crypto engine sideload interfaces, and the ML-KEM shared-key read/consume
 * interface. Write-key logic for dual-share engines is shared via the static
 * sideload_write_dual_share() helper.
 */

#include "rom_sideload.h"
#include "rom_defs.h"
#include "rom_prng.h"
#include "rom_shred.h"
#include "rom_drbg.h"
#include "rom_shuffle.h"
#include "rom_secutil.h"
#include "key_manager_fw.h"

/*===========================================================================
 * Key valid bit accessors
 *===========================================================================*/

/** @brief Clear the HMAC key valid bit. */
void rom_hmac_key_valid_clear(void) {
    ROM_HMAC_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the HMAC key valid bit. */
void rom_hmac_key_valid_set(void) {
    ROM_HMAC_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the KMAC key valid bit. */
void rom_kmac_key_valid_clear(void) {
    ROM_KMAC_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the KMAC key valid bit. */
void rom_kmac_key_valid_set(void) {
    ROM_KMAC_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the AES key valid bit. */
void rom_aes_key_valid_clear(void) {
    ROM_AES_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the AES key valid bit. */
void rom_aes_key_valid_set(void) {
    ROM_AES_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the OTBN key valid bit. */
void rom_otbn_key_valid_clear(void) {
    ROM_OTBN_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the OTBN key valid bit. */
void rom_otbn_key_valid_set(void) {
    ROM_OTBN_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the ABR ML-DSA seed key valid bit. */
void rom_abr_mldsa_seed_key_valid_clear(void) {
    ROM_ABR_MLDSA_SEED_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the ABR ML-DSA seed key valid bit. */
void rom_abr_mldsa_seed_key_valid_set(void) {
    ROM_ABR_MLDSA_SEED_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the ABR ML-KEM seed-D key valid bit. */
void rom_abr_mlkem_seed_d_key_valid_clear(void) {
    ROM_ABR_MLKEM_SEED_D_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the ABR ML-KEM seed-D key valid bit. */
void rom_abr_mlkem_seed_d_key_valid_set(void) {
    ROM_ABR_MLKEM_SEED_D_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the ABR ML-KEM seed-Z key valid bit. */
void rom_abr_mlkem_seed_z_key_valid_clear(void) {
    ROM_ABR_MLKEM_SEED_Z_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the ABR ML-KEM seed-Z key valid bit. */
void rom_abr_mlkem_seed_z_key_valid_set(void) {
    ROM_ABR_MLKEM_SEED_Z_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the ABR ML-KEM message key valid bit. */
void rom_abr_mlkem_msg_key_valid_clear(void) {
    ROM_ABR_MLKEM_MSG_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the ABR ML-KEM message key valid bit. */
void rom_abr_mlkem_msg_key_valid_set(void) {
    ROM_ABR_MLKEM_MSG_KEY_CTRL_REG.f.key_valid = 1;
}

/*===========================================================================
 * Common helper
 *===========================================================================*/

/**
 * @brief Write dual XOR-masked shares to an engine (common helper).
 *
 * Pads key to @p n words with DRBG, generates random mask, shuffles
 * write order, and writes SHARE0[i]=rand[i], SHARE1[i]=padded[i]^rand[i].
 * Caller must set key_valid after this returns.
 *
 * @param[out] share0   Base of SHARE0 register bank (n words).
 * @param[out] share1   Base of SHARE1 register bank (n words).
 * @param[in]  n        Words per share (1..ROM_KM_OTBN_WORDS_PER_SHARE).
 * @param[in]  key      Key data (key_len words).
 * @param[in]  key_len  Key length in words.
 * @param[in,out] prng  PRNG state for shuffle.
 * @return 0 on success; -1 if @p n exceeds ROM_KM_MAX_WORDS_PER_SHARE (the
 *         fixed share-buffer size).
 */
static int sideload_write_dual_share(volatile uint32_t *share0, volatile uint32_t *share1,
                                     uint8_t n, const uint32_t *key, uint8_t key_len,
                                     rom_km_prng_state_t *prng) {
    if (n > ROM_KM_MAX_WORDS_PER_SHARE) return -1;

    uint32_t padded[ROM_KM_MAX_WORDS_PER_SHARE];
    uint32_t rand_mask[ROM_KM_MAX_WORDS_PER_SHARE];
    uint16_t order[2 * ROM_KM_MAX_WORDS_PER_SHARE];

    for (uint8_t i = 0; i < n; i++) padded[i] = (i < key_len) ? key[i] : rom_drbg_get_word();

    rom_drbg_get_block(rand_mask, n);

    rom_shuffle_init_array(prng, order, (uint16_t)(2 * n));

    for (uint8_t j = 0; j < 2 * n; j++) {
        uint8_t idx = (uint8_t)order[j];
        uint8_t word = idx / 2;
        if (idx & 1)
            share1[word] = padded[word] ^ rand_mask[word];
        else
            share0[word] = rand_mask[word];
    }

    /* Clear the plaintext key (padded) and its mask from the stack. Only the
     * first n words of each buffer were populated. */
    rom_secure_memzero(padded, (size_t)n * sizeof(padded[0]));
    rom_secure_memzero(rand_mask, (size_t)n * sizeof(rand_mask[0]));

    return 0;
}

/* ============================================================================
 * HMAC
 * ============================================================================ */

/** @brief Total words to shred in HMAC engine (both shares). */
#define ROM_HMAC_SHRED_WORD_LEN ((uint8_t)(ROM_KM_HMAC_WORDS_PER_SHARE * 2))

/**
 * @brief Shred HMAC sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_hmac_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_hmac_key_valid_clear();
    rom_shred_region((volatile uint32_t *)(KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR +
                                           ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
                     ROM_HMAC_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to HMAC sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_HMAC_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_hmac_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 = (volatile uint32_t *)(KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR +
                                                  ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR +
                              ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_HMAC_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_HMAC_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_hmac_key_valid_set();
    return 0;
}

/* ============================================================================
 * KMAC
 * ============================================================================ */

/** @brief Total words to shred in KMAC engine (both shares). */
#define ROM_KMAC_SHRED_WORD_LEN ((uint8_t)(ROM_KM_KMAC_WORDS_PER_SHARE * 2))

/**
 * @brief Shred KMAC sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_kmac_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_kmac_key_valid_clear();
    rom_shred_region((volatile uint32_t *)(KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR +
                                           ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
                     ROM_KMAC_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to KMAC sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_KMAC_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_kmac_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 = (volatile uint32_t *)(KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR +
                                                  ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR +
                              ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_KMAC_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_KMAC_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_kmac_key_valid_set();
    return 0;
}

/* ============================================================================
 * AES
 * ============================================================================ */

/** @brief Total words to shred in AES engine (both shares). */
#define ROM_AES_SHRED_WORD_LEN ((uint8_t)(ROM_KM_AES_WORDS_PER_SHARE * 2))

/**
 * @brief Shred AES sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_aes_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_aes_key_valid_clear();
    rom_shred_region((volatile uint32_t *)(KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR +
                                           ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
                     ROM_AES_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to AES sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_AES_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_aes_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 = (volatile uint32_t *)(KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR +
                                                  ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR +
                              ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_AES_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_AES_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_aes_key_valid_set();
    return 0;
}

/* ============================================================================
 * OTBN
 * ============================================================================ */

/** @brief Total words to shred in OTBN engine (both shares). */
#define ROM_OTBN_SHRED_WORD_LEN ((uint8_t)(ROM_KM_OTBN_WORDS_PER_SHARE * 2))

/**
 * @brief Shred OTBN sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_otbn_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_otbn_key_valid_clear();
    rom_shred_region((volatile uint32_t *)(KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR +
                                           ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
                     ROM_OTBN_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to OTBN sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_OTBN_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_otbn_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 = (volatile uint32_t *)(KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR +
                                                  ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR +
                              ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_OTBN_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_OTBN_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_otbn_key_valid_set();
    return 0;
}

/* ============================================================================
 * Adams Bridge MLDSA_SEED
 * ============================================================================ */

/** @brief Total words to shred in ABR MLDSA_SEED (both shares). */
#define ROM_ABR_MLDSA_SEED_SHRED_WORD_LEN ((uint8_t)(ROM_KM_ABR_WORDS_PER_SHARE * 2))

/**
 * @brief Shred Adams Bridge ML-DSA seed with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mldsa_seed_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_abr_mldsa_seed_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLDSA_SEED_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_ABR_MLDSA_SEED_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to Adams Bridge ML-DSA seed (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mldsa_seed_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLDSA_SEED_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLDSA_SEED_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE1_OFFSET(
                                             ROM_KM_ABR_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_ABR_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_abr_mldsa_seed_key_valid_set();
    return 0;
}

/* ============================================================================
 * Adams Bridge MLKEM_SEED_D
 * ============================================================================ */

/** @brief Total words to shred in ABR MLKEM_SEED_D (both shares). */
#define ROM_ABR_MLKEM_SEED_D_SHRED_WORD_LEN ((uint8_t)(ROM_KM_ABR_WORDS_PER_SHARE * 2))

/**
 * @brief Shred Adams Bridge ML-KEM seed-D with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mlkem_seed_d_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_abr_mlkem_seed_d_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_D_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_ABR_MLKEM_SEED_D_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to Adams Bridge ML-KEM seed-D (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mlkem_seed_d_write_key(const uint32_t *key, uint8_t key_len,
                                   rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_D_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_D_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE1_OFFSET(
                                             ROM_KM_ABR_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_ABR_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_abr_mlkem_seed_d_key_valid_set();
    return 0;
}

/* ============================================================================
 * Adams Bridge MLKEM_SEED_Z
 * ============================================================================ */

/** @brief Total words to shred in ABR MLKEM_SEED_Z (both shares). */
#define ROM_ABR_MLKEM_SEED_Z_SHRED_WORD_LEN ((uint8_t)(ROM_KM_ABR_WORDS_PER_SHARE * 2))

/**
 * @brief Shred Adams Bridge ML-KEM seed-Z with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mlkem_seed_z_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_abr_mlkem_seed_z_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_Z_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_ABR_MLKEM_SEED_Z_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to Adams Bridge ML-KEM seed-Z (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mlkem_seed_z_write_key(const uint32_t *key, uint8_t key_len,
                                   rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_Z_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_Z_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE1_OFFSET(
                                             ROM_KM_ABR_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_ABR_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_abr_mlkem_seed_z_key_valid_set();
    return 0;
}

/* ============================================================================
 * Adams Bridge MLKEM_MSG
 * ============================================================================ */

/** @brief Total words to shred in ABR MLKEM_MSG (both shares). */
#define ROM_ABR_MLKEM_MSG_SHRED_WORD_LEN ((uint8_t)(ROM_KM_ABR_WORDS_PER_SHARE * 2))

/**
 * @brief Shred Adams Bridge ML-KEM message with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mlkem_msg_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed) {
    rom_abr_mlkem_msg_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_MSG_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_ABR_MLKEM_MSG_SHRED_WORD_LEN, prng, allow_reseed);
}

/**
 * @brief Write key to Adams Bridge ML-KEM message (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mlkem_msg_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng) {
    volatile uint32_t *s0 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_MSG_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 =
        (volatile uint32_t *)(uintptr_t)(KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_MSG_BASE_ADDR +
                                         ROM_KM_ENGINE_KEY_SHARE1_OFFSET(
                                             ROM_KM_ABR_WORDS_PER_SHARE));
    if (sideload_write_dual_share(s0, s1, ROM_KM_ABR_WORDS_PER_SHARE, key, key_len, prng) < 0)
        return -1;
    rom_abr_mlkem_msg_key_valid_set();
    return 0;
}

/* ============================================================================
 * Adams Bridge — ML-KEM shared-key sub-block
 * ============================================================================ */

/** @brief Enable the ML-KEM shared-key interrupt. */
void rom_abr_mlkem_sharedkey_irq_enable(void) {
    ROM_ABR_MLKEM_SK_IRQ_ENABLE_REG.f.key_valid_en = 1;
}

/** @brief Disable the ML-KEM shared-key interrupt. */
void rom_abr_mlkem_sharedkey_irq_disable(void) {
    ROM_ABR_MLKEM_SK_IRQ_ENABLE_REG.f.key_valid_en = 0;
}

/** @brief Acknowledge the ML-KEM shared-key interrupt (clear sticky status, W1C). */
void rom_abr_mlkem_sharedkey_irq_status_clear(void) {
    abr_wrapper_key__sk_irq_status_reg_t w = {.w = 0};
    w.f.key_valid = 1; /* write 1 to clear the sticky status bit */
    ROM_ABR_MLKEM_SK_IRQ_STATUS_REG.w = w.w;
}

/**
 * @brief Read the ML-KEM shared key and consume it (clear valid + zeroize).
 *
 * Reads KEY[0..7] into @p out_key, then writes KEY_CTRL = 0 to clear KEY_VALID
 * (hardware zeroizes KEY[*] via hwclr).
 *
 * @param[out] out_key Output buffer for the 8-word (256-bit) shared key.
 */
void rom_abr_mlkem_sharedkey_read(uint32_t out_key[ROM_KM_ABR_WORDS_PER_SHARE]) {
    volatile uint32_t *key_regs =
        (volatile uint32_t *)(uintptr_t)KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_BASE_ADDR;

    for (uint8_t i = 0; i < ROM_KM_ABR_WORDS_PER_SHARE; i++) out_key[i] = key_regs[i];

    ROM_ABR_MLKEM_SK_CTRL_REG.w = 0;
}

/**
 * @brief Zeroize the ML-KEM shared key without reading it (teardown path).
 *
 * Writes KEY_CTRL = 0 to clear KEY_VALID (wzc) and trigger hardware zeroize of
 * KEY[*] (hwclr), discarding any key delivered but not yet consumed.
 */
void rom_abr_mlkem_sharedkey_zeroize(void) {
    ROM_ABR_MLKEM_SK_CTRL_REG.w = 0;
}
