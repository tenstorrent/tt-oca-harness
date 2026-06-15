/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_sideload.c
 * @brief Combined crypto-engine sideload key driver (HMAC, KMAC, AES, OTBN)
 *
 * Implements shred_key and write_key for all four engines. Share and
 * control register addresses use ROM_KM_*_WRAPPER_BASE and the common
 * engine layout in rom_defs.h. Write-key logic is shared via
 * sideload_write_dual_share().
 */

#include "rom_sideload.h"
#include "rom_defs.h"
#include "rom_prng.h"
#include "rom_shred.h"
#include "rom_drbg.h"
#include "rom_shuffle.h"
#include "key_manager_regs.h"

/*===========================================================================
 * Key valid bit accessors
 *===========================================================================*/

/** @brief Clear the HMAC key valid bit. */
void rom_hmac_key_valid_clear(void)
{
    ROM_HMAC_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the HMAC key valid bit. */
void rom_hmac_key_valid_set(void)
{
    ROM_HMAC_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the KMAC key valid bit. */
void rom_kmac_key_valid_clear(void)
{
    ROM_KMAC_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the KMAC key valid bit. */
void rom_kmac_key_valid_set(void)
{
    ROM_KMAC_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the AES key valid bit. */
void rom_aes_key_valid_clear(void)
{
    ROM_AES_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the AES key valid bit. */
void rom_aes_key_valid_set(void)
{
    ROM_AES_KEY_CTRL_REG.f.key_valid = 1;
}

/** @brief Clear the OTBN key valid bit. */
void rom_otbn_key_valid_clear(void)
{
    ROM_OTBN_KEY_CTRL_REG.f.key_valid = 0;
}

/** @brief Set the OTBN key valid bit. */
void rom_otbn_key_valid_set(void)
{
    ROM_OTBN_KEY_CTRL_REG.f.key_valid = 1;
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
 */
static void sideload_write_dual_share(volatile uint32_t *share0,
                                     volatile uint32_t *share1,
                                     uint8_t n,
                                     const uint32_t *key,
                                     uint8_t key_len,
                                     rom_km_prng_state_t *prng)
{
    uint32_t padded[n];
    uint32_t rand_mask[n];
    uint16_t order[2 * n];

    for (uint8_t i = 0; i < n; i++)
        padded[i] = (i < key_len) ? key[i] : rom_drbg_get_word();

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
}

/* ============================================================================
 * HMAC
 * ============================================================================ */

/** @brief Total words to shred in HMAC engine (both shares). */
#define ROM_HMAC_SHRED_WORD_LEN  ((uint8_t)(ROM_KM_HMAC_WORDS_PER_SHARE * 2))

/**
 * @brief Shred HMAC sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_hmac_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed)
{
    rom_hmac_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(ROM_KM_HMAC_WRAPPER_BASE + ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_HMAC_SHRED_WORD_LEN,
        prng,
        allow_reseed);
}

/**
 * @brief Write key to HMAC sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_HMAC_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 */
void rom_hmac_write_key(const uint32_t *key, uint8_t key_len,
                        rom_km_prng_state_t *prng)
{
    volatile uint32_t *s0 = (volatile uint32_t *)(ROM_KM_HMAC_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 = (volatile uint32_t *)(ROM_KM_HMAC_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_HMAC_WORDS_PER_SHARE));
    sideload_write_dual_share(s0, s1, ROM_KM_HMAC_WORDS_PER_SHARE, key, key_len, prng);
    rom_hmac_key_valid_set();
}

/* ============================================================================
 * KMAC
 * ============================================================================ */

/** @brief Total words to shred in KMAC engine (both shares). */
#define ROM_KMAC_SHRED_WORD_LEN  ((uint8_t)(ROM_KM_KMAC_WORDS_PER_SHARE * 2))

/**
 * @brief Shred KMAC sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_kmac_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed)
{
    rom_kmac_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(ROM_KM_KMAC_WRAPPER_BASE + ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_KMAC_SHRED_WORD_LEN,
        prng,
        allow_reseed);
}

/**
 * @brief Write key to KMAC sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_KMAC_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 */
void rom_kmac_write_key(const uint32_t *key, uint8_t key_len,
                        rom_km_prng_state_t *prng)
{
    volatile uint32_t *s0 = (volatile uint32_t *)(ROM_KM_KMAC_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 = (volatile uint32_t *)(ROM_KM_KMAC_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_KMAC_WORDS_PER_SHARE));
    sideload_write_dual_share(s0, s1, ROM_KM_KMAC_WORDS_PER_SHARE, key, key_len, prng);
    rom_kmac_key_valid_set();
}

/* ============================================================================
 * AES
 * ============================================================================ */

/** @brief Total words to shred in AES engine (both shares). */
#define ROM_AES_SHRED_WORD_LEN  ((uint8_t)(ROM_KM_AES_WORDS_PER_SHARE * 2))

/**
 * @brief Shred AES sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_aes_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed)
{
    rom_aes_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(ROM_KM_AES_WRAPPER_BASE + ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_AES_SHRED_WORD_LEN,
        prng,
        allow_reseed);
}

/**
 * @brief Write key to AES sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_AES_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 */
void rom_aes_write_key(const uint32_t *key, uint8_t key_len,
                       rom_km_prng_state_t *prng)
{
    volatile uint32_t *s0 = (volatile uint32_t *)(ROM_KM_AES_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 = (volatile uint32_t *)(ROM_KM_AES_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_AES_WORDS_PER_SHARE));
    sideload_write_dual_share(s0, s1, ROM_KM_AES_WORDS_PER_SHARE, key, key_len, prng);
    rom_aes_key_valid_set();
}

/* ============================================================================
 * OTBN
 * ============================================================================ */

/** @brief Total words to shred in OTBN engine (both shares). */
#define ROM_OTBN_SHRED_WORD_LEN  ((uint8_t)(ROM_KM_OTBN_WORDS_PER_SHARE * 2))

/**
 * @brief Shred OTBN sideload key with pseudorandom data and clear key_valid.
 *
 * @param[in,out] prng        PRNG state; reseeded from DRBG if allow_reseed.
 * @param[in]     allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_otbn_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed)
{
    rom_otbn_key_valid_clear();
    rom_shred_region(
        (volatile uint32_t *)(ROM_KM_OTBN_WRAPPER_BASE + ROM_KM_ENGINE_KEY_SHARE0_OFFSET),
        ROM_OTBN_SHRED_WORD_LEN,
        prng,
        allow_reseed);
}

/**
 * @brief Write key to OTBN sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param[in]     key     Key data (key_len words).
 * @param[in]     key_len Key length in words (1..ROM_KM_OTBN_WORDS_PER_SHARE).
 * @param[in,out] prng    PRNG state for shuffle.
 */
void rom_otbn_write_key(const uint32_t *key, uint8_t key_len,
                        rom_km_prng_state_t *prng)
{
    volatile uint32_t *s0 = (volatile uint32_t *)(ROM_KM_OTBN_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE0_OFFSET);
    volatile uint32_t *s1 = (volatile uint32_t *)(ROM_KM_OTBN_WRAPPER_BASE +
        ROM_KM_ENGINE_KEY_SHARE1_OFFSET(ROM_KM_OTBN_WORDS_PER_SHARE));
    sideload_write_dual_share(s0, s1, ROM_KM_OTBN_WORDS_PER_SHARE, key, key_len, prng);
    rom_otbn_key_valid_set();
}
