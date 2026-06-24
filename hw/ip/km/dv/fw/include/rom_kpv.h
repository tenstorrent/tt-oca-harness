/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kpv.h
 * @brief Key Provisioning Vault (KPV) driver for Key Manager firmware
 *
 * Provides scrambler initialization/control, slot shredding, key read/write,
 * and write/read locking through the PeakRDL-generated register unions in
 * km.h / km_addr.h.
 */

#ifndef ROM_KPV_H
#define ROM_KPV_H

#include <stdint.h>
#include "rom_defs.h"
#include "rom_prng.h"
#include "km.h"
#include "km_addr.h"

/*===========================================================================
 * Indexed Register Access Macros
 *===========================================================================*/

/** @brief Access KPV key data word [word] in slot [slot]. */
#define KPV_KEY_WORD(slot, word) \
    (*(volatile uint32_t *)(KEY_MANAGER_KPV_KEY_ENTRY_WORD_BASE_ADDR(0, 0) + (slot) * 0x40 + (word) * 4))

/** @brief Access KPV control register for slot [slot]. */
#define KPV_CTRL(slot) \
    (*(volatile km_kpv__ctrl_reg_t *)(KEY_MANAGER_KPV_CTRL_BASE_ADDR(0) + (slot) * 4))

/*===========================================================================
 * Scrambler Functions
 *===========================================================================*/

/**
 * @brief Initialize the KPV scrambler.
 *
 * Writes the scrambler key register SHRED_ITER+1 times with DRBG-sourced
 * random words.  Skipped if the scrambler is already locked.
 */
void rom_kpv_init_scrambler(void);

/**
 * @brief Enable the KPV scrambler.
 */
void rom_kpv_scrambler_enable(void);

/**
 * @brief Disable the KPV scrambler (no-op if already locked).
 *
 * Used by tests to read back raw stored data and verify scrambling.
 */
void rom_kpv_scrambler_disable(void);

/**
 * @brief Lock the KPV scrambler (irreversible until reset).
 */
void rom_kpv_scrambler_lock(void);

/*===========================================================================
 * Shred Functions
 *===========================================================================*/

/**
 * @brief Shred all KPV slots.
 *
 * If any slot is write-locked, returns -1 without shredding.  Otherwise
 * clears slot control registers and shreds the entire key array (512 words)
 * in one call to rom_shred_region (SHRED_ITER+1 passes, reseed from DRBG
 * each pass).
 *
 * @param prng Firmware PRNG state (reseeded each pass).
 * @return 0 on success, -1 if any slot is write-locked.
 */
int rom_kpv_shred_all(rom_km_prng_state_t *prng);

/**
 * @brief Shred a single KPV slot.
 *
 * Clears the slot control register (error if write-locked), then writes
 * PRNG-sourced random data in pseudorandom word order for SHRED_ITER+1
 * passes, reseeding the PRNG from the DRBG before each pass.
 *
 * @param slot Slot index (0-31).
 * @param prng Firmware PRNG state (reseeded each pass).
 * @return 0 on success, -1 if the slot is write-locked.
 */
int rom_kpv_shred_slot(uint8_t slot, rom_km_prng_state_t *prng);

/*===========================================================================
 * Key Data Functions
 *===========================================================================*/

/**
 * @brief Write key data and control fields to the KPV.
 *
 * Computes EXTEND = (key_len-1)/16, sets LAST_DWORD and DEST_VALID on
 * each required slot, and writes the key words.  Returns an error if any
 * required slot is write-locked (no data is written in that case).
 *
 * @param base_slot Base slot index (0-31).
 * @param key Key data (key_len 32-bit words).
 * @param key_len Key length in 32-bit words (1-128).
 * @param dest_valid Permitted crypto-engine destination bitmask.
 * @return 0 on success, -1 on error.
 */
int rom_kpv_write_key(uint8_t base_slot, const uint32_t *key,
                      uint8_t key_len, rom_km_dest_bits_t dest_valid);

/**
 * @brief Get key length and dest_valid from KPV control registers (no key data read).
 *
 * Same validation as rom_kpv_read_key (lock_use, last_dword).
 *
 * @param base_slot Base slot index (0-31).
 * @param key_len Receives total key length in 32-bit words.
 * @param dest_valid Receives permitted destination bitmask.
 * @return 0 on success, -1 if any slot is read-locked or control fields malformed.
 */
int rom_kpv_get_key_info(uint8_t base_slot, uint8_t *key_len, rom_km_dest_bits_t *dest_valid);

/**
 * @brief Read key data and control fields from the KPV.
 *
 * Reconstructs total key length from EXTEND and LAST_DWORD, verifies that
 * non-final slots have LAST_DWORD == 15, and copies key words into @p key.
 * Returns an error if any required slot is read-locked.
 *
 * @param base_slot Base slot index (0-31).
 * @param key Buffer for key data (caller must size appropriately).
 * @param key_len Receives total key length in 32-bit words.
 * @param dest_valid Receives permitted destination bitmask.
 * @return 0 on success, -1 on error.
 */
int rom_kpv_read_key(uint8_t base_slot, uint32_t *key,
                     uint8_t *key_len, rom_km_dest_bits_t *dest_valid);

/*===========================================================================
 * Lock Functions
 *===========================================================================*/

/**
 * @brief Write-lock the base slot and all extended slots.
 * @param base_slot Base slot index (0-31).
 */
void rom_kpv_write_lock(uint8_t base_slot);

/**
 * @brief Read-lock (lock_use) the base slot and all extended slots.
 * @param base_slot Base slot index (0-31).
 */
void rom_kpv_read_lock(uint8_t base_slot);

#endif /* ROM_KPV_H */
