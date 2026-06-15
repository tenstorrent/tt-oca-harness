/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_sideload.h
 * @brief Combined crypto-engine sideload key driver (HMAC, KMAC, AES, OTBN)
 *
 * Single header for all four engines: key_valid clear/set, shred_key and
 * write_key.
 */

#ifndef ROM_SIDELOAD_H
#define ROM_SIDELOAD_H

#include <stdint.h>
#include "rom_defs.h"
#include "rom_prng.h"
#include "key_manager_regs.h"

/* ============================================================================
 * HMAC (PeakRDL KEY_CTRL)
 * ============================================================================ */

/** @brief HMAC key control register (volatile). */
#define ROM_HMAC_KEY_CTRL_REG \
    (*(volatile HMAC_WRAPPER_KEY_KEY_CTRL_REG_reg_u *)HMAC_WRAPPER_KEY_KEY_CTRL_REG_ADDR)

/** @brief Clear the HMAC key valid bit. */
void rom_hmac_key_valid_clear(void);

/** @brief Set the HMAC key valid bit. */
void rom_hmac_key_valid_set(void);

/**
 * @brief Shred HMAC sideload key with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_hmac_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to HMAC sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_HMAC_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 */
void rom_hmac_write_key(const uint32_t *key, uint8_t key_len,
                        rom_km_prng_state_t *prng);

/* ============================================================================
 * KMAC (PeakRDL KEY_CTRL)
 * ============================================================================ */

/** @brief KMAC key control register (volatile). */
#define ROM_KMAC_KEY_CTRL_REG \
    (*(volatile KMAC_WRAPPER_KEY_KEY_CTRL_REG_reg_u *)KMAC_WRAPPER_KEY_KEY_CTRL_REG_ADDR)

/** @brief Clear the KMAC key valid bit. */
void rom_kmac_key_valid_clear(void);

/** @brief Set the KMAC key valid bit. */
void rom_kmac_key_valid_set(void);

/**
 * @brief Shred KMAC sideload key with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_kmac_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to KMAC sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_KMAC_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 */
void rom_kmac_write_key(const uint32_t *key, uint8_t key_len,
                        rom_km_prng_state_t *prng);

/* ============================================================================
 * AES (PeakRDL KEY_CTRL)
 * ============================================================================ */

/** @brief AES key control register (volatile). */
#define ROM_AES_KEY_CTRL_REG \
    (*(volatile AES_WRAPPER_KEY_KEY_CTRL_REG_reg_u *)AES_WRAPPER_KEY_KEY_CTRL_REG_ADDR)

/** @brief Clear the AES key valid bit. */
void rom_aes_key_valid_clear(void);

/** @brief Set the AES key valid bit. */
void rom_aes_key_valid_set(void);

/**
 * @brief Shred AES sideload key with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_aes_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to AES sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_AES_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 */
void rom_aes_write_key(const uint32_t *key, uint8_t key_len,
                       rom_km_prng_state_t *prng);

/* ============================================================================
 * OTBN (PeakRDL KEY_CTRL; 12 words per share)
 * ============================================================================ */

/** @brief OTBN key control register (volatile). */
#define ROM_OTBN_KEY_CTRL_REG \
    (*(volatile OTBN_WRAPPER_KEY_KEY_CTRL_REG_reg_u *)OTBN_WRAPPER_KEY_KEY_CTRL_REG_ADDR)

/** @brief Clear the OTBN key valid bit. */
void rom_otbn_key_valid_clear(void);

/** @brief Set the OTBN key valid bit. */
void rom_otbn_key_valid_set(void);

/**
 * @brief Shred OTBN sideload key with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_otbn_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to OTBN sideload (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_OTBN_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 */
void rom_otbn_write_key(const uint32_t *key, uint8_t key_len,
                        rom_km_prng_state_t *prng);

#endif /* ROM_SIDELOAD_H */
