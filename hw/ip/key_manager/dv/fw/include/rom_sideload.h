/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_sideload.h
 * @brief Crypto-engine sideload key driver
 *
 * Sideload key drivers for all KM crypto engine interfaces: seed write,
 * key_valid control, shred, and (for ML-KEM) shared-key read/consume.
 */

#ifndef ROM_SIDELOAD_H
#define ROM_SIDELOAD_H

#include <stdint.h>
#include "rom_defs.h"
#include "rom_prng.h"
#include "key_manager_fw.h"

/* ============================================================================
 * HMAC (PeakRDL KEY_CTRL)
 * ============================================================================ */

/** @brief HMAC key control register (volatile). */
#define ROM_HMAC_KEY_CTRL_REG \
    (*(volatile hmac_wrapper_key__key_ctrl_reg_t *)KEY_MANAGER_HMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)

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
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_hmac_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * KMAC (PeakRDL KEY_CTRL)
 * ============================================================================ */

/** @brief KMAC key control register (volatile). */
#define ROM_KMAC_KEY_CTRL_REG \
    (*(volatile kmac_wrapper_key__key_ctrl_reg_t *)KEY_MANAGER_KMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)

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
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_kmac_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * AES (PeakRDL KEY_CTRL)
 * ============================================================================ */

/** @brief AES key control register (volatile). */
#define ROM_AES_KEY_CTRL_REG \
    (*(volatile aes_wrapper_key__key_ctrl_reg_t *)KEY_MANAGER_AES_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)

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
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_aes_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * OTBN (PeakRDL KEY_CTRL; 12 words per share)
 * ============================================================================ */

/** @brief OTBN key control register (volatile). */
#define ROM_OTBN_KEY_CTRL_REG \
    (*(volatile otbn_wrapper_key__key_ctrl_reg_t *)KEY_MANAGER_OTBN_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)

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
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_otbn_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * Adams Bridge MLDSA_SEED (ML-DSA-87 seed input, 8 words per share)
 * ============================================================================ */

/** @brief ABR MLDSA_SEED key control register (volatile). */
#define ROM_ABR_MLDSA_SEED_KEY_CTRL_REG \
    (*(volatile abr_wrapper_key__seed_ctrl_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLDSA_SEED_KEY_CTRL_BASE_ADDR)

/** @brief Clear the MLDSA_SEED key valid bit. */
void rom_abr_mldsa_seed_key_valid_clear(void);

/** @brief Set the MLDSA_SEED key valid bit. */
void rom_abr_mldsa_seed_key_valid_set(void);

/**
 * @brief Shred Adams Bridge ML-DSA seed with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mldsa_seed_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to Adams Bridge ML-DSA seed (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mldsa_seed_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * Adams Bridge MLKEM_SEED_D (ML-KEM-1024 seed d input, 8 words per share)
 * ============================================================================ */

/** @brief ABR MLKEM_SEED_D key control register (volatile). */
#define ROM_ABR_MLKEM_SEED_D_KEY_CTRL_REG \
    (*(volatile abr_wrapper_key__seed_ctrl_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_D_KEY_CTRL_BASE_ADDR)

/** @brief Clear the MLKEM_SEED_D key valid bit. */
void rom_abr_mlkem_seed_d_key_valid_clear(void);

/** @brief Set the MLKEM_SEED_D key valid bit. */
void rom_abr_mlkem_seed_d_key_valid_set(void);

/**
 * @brief Shred Adams Bridge ML-KEM seed-D with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mlkem_seed_d_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to Adams Bridge ML-KEM seed-D (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mlkem_seed_d_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * Adams Bridge MLKEM_SEED_Z (ML-KEM-1024 seed z input, 8 words per share)
 * ============================================================================ */

/** @brief ABR MLKEM_SEED_Z key control register (volatile). */
#define ROM_ABR_MLKEM_SEED_Z_KEY_CTRL_REG \
    (*(volatile abr_wrapper_key__seed_ctrl_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SEED_Z_KEY_CTRL_BASE_ADDR)

/** @brief Clear the MLKEM_SEED_Z key valid bit. */
void rom_abr_mlkem_seed_z_key_valid_clear(void);

/** @brief Set the MLKEM_SEED_Z key valid bit. */
void rom_abr_mlkem_seed_z_key_valid_set(void);

/**
 * @brief Shred Adams Bridge ML-KEM seed-Z with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mlkem_seed_z_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to Adams Bridge ML-KEM seed-Z (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mlkem_seed_z_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * Adams Bridge MLKEM_MSG (ML-KEM-1024 message input, 8 words per share)
 * ============================================================================ */

/** @brief ABR MLKEM_MSG key control register (volatile). */
#define ROM_ABR_MLKEM_MSG_KEY_CTRL_REG \
    (*(volatile abr_wrapper_key__seed_ctrl_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_MSG_KEY_CTRL_BASE_ADDR)

/** @brief Clear the MLKEM_MSG key valid bit. */
void rom_abr_mlkem_msg_key_valid_clear(void);

/** @brief Set the MLKEM_MSG key valid bit. */
void rom_abr_mlkem_msg_key_valid_set(void);

/**
 * @brief Shred Adams Bridge ML-KEM message with pseudorandom data and clear key_valid.
 *
 * @param prng PRNG state; reseeded from DRBG if allow_reseed.
 * @param allow_reseed Non-zero to reseed PRNG each shred pass; 0 for wipe path.
 */
void rom_abr_mlkem_msg_shred_key(rom_km_prng_state_t *prng, uint8_t allow_reseed);

/**
 * @brief Write key to Adams Bridge ML-KEM message (dual XOR-masked shares) and set key_valid.
 *
 * @param key Key data (key_len words).
 * @param key_len Key length in words (1..ROM_KM_ABR_WORDS_PER_SHARE).
 * @param prng PRNG state for shuffle.
 * @return 0 on success; -1 if the share write fails (key_valid left clear).
 */
int rom_abr_mlkem_msg_write_key(const uint32_t *key, uint8_t key_len, rom_km_prng_state_t *prng);

/* ============================================================================
 * Adams Bridge MLKEM_SHARED_KEY (ML-KEM shared key output, HW→SW)
 *
 * Reverse direction: Adams Bridge writes KEY[8] and sets KEY_VALID when
 * encaps/decaps completes. Firmware reads the key then clears KEY_CTRL
 * (write 0) to consume and zeroize.
 * ============================================================================ */

/** @brief ABR MLKEM_SHARED_KEY control register (volatile). */
#define ROM_ABR_MLKEM_SK_CTRL_REG \
    (*(volatile abr_wrapper_key__sk_ctrl_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_KEY_CTRL_BASE_ADDR)

/** @brief ABR MLKEM_SHARED_KEY IRQ enable register (volatile). */
#define ROM_ABR_MLKEM_SK_IRQ_ENABLE_REG \
    (*(volatile abr_wrapper_key__sk_irq_enable_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_IRQ_ENABLE_BASE_ADDR)

/** @brief ABR MLKEM_SHARED_KEY IRQ status register (volatile). */
#define ROM_ABR_MLKEM_SK_IRQ_STATUS_REG \
    (*(volatile abr_wrapper_key__sk_irq_status_reg_t *) \
         KEY_MANAGER_ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_IRQ_STATUS_BASE_ADDR)

/**
 * @brief Read the ML-KEM shared key and consume it (clear valid + zeroize).
 *
 * Reads all 8 key words into @p out_key, then writes KEY_CTRL = 0 which
 * clears KEY_VALID (via wzc) and triggers hardware zeroize of KEY[*] (hwclr).
 *
 * @param out_key  Output buffer for the 8-word (256-bit) shared key.
 */
void rom_abr_mlkem_sharedkey_read(uint32_t out_key[ROM_KM_ABR_WORDS_PER_SHARE]);

/**
 * @brief Zeroize the ML-KEM shared key without reading it (teardown path).
 *
 * Writes KEY_CTRL = 0 which clears KEY_VALID (via wzc) and triggers hardware
 * zeroize of KEY[*] (hwclr). Used on boot-wipe, fault, and handover paths so a
 * shared key delivered but not yet consumed leaves no residual material.
 */
void rom_abr_mlkem_sharedkey_zeroize(void);

/** @brief Enable the ML-KEM shared-key interrupt (IRQ_ENABLE.KEY_VALID_EN = 1). */
void rom_abr_mlkem_sharedkey_irq_enable(void);

/** @brief Disable the ML-KEM shared-key interrupt (IRQ_ENABLE.KEY_VALID_EN = 0). */
void rom_abr_mlkem_sharedkey_irq_disable(void);

/**
 * @brief Acknowledge the ML-KEM shared-key interrupt.
 *
 * Clears the sticky IRQ_STATUS.KEY_VALID bit by writing 1 (W1C).
 */
void rom_abr_mlkem_sharedkey_irq_status_clear(void);

#endif /* ROM_SIDELOAD_H */
