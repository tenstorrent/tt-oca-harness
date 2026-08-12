/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_keyreg.h
 * @brief Key handle registry for Key Manager firmware
 *
 * Maps monotonically-increasing 8-bit key handles (1-255) to KPV base slots,
 * with a reverse slot-to-handle map for fast slot-based queries.  Handle 0 is
 * reserved as the null handle and is never assigned.  Provides allocation
 * (generate), lookup (get_handle / get_slot / get_crc / get_dest_valid /
 * get_key_words), and destruction (destroy).  Key length is recorded here too:
 * the KPV stores key data only, so a key's extent is software state that
 * callers read back from this registry.
 */

#ifndef ROM_KEYREG_H
#define ROM_KEYREG_H

#include <stdint.h>
#include "rom_defs.h"

/*===========================================================================
 * Types
 *===========================================================================*/

/**
 * @brief KPV slots occupied by a key of @p key_words 32-bit words.
 *
 * Keys are stored in a contiguous run of slots starting at the base slot, so
 * the span is the word count rounded up to a whole slot.
 */
#define ROM_KM_KEY_SLOT_SPAN(key_words) \
    ((uint8_t)(((key_words) + ROM_KM_KPV_WORDS_PER_SLOT - 1) / ROM_KM_KPV_WORDS_PER_SLOT))

/** @brief Slots occupied by the largest supported key. */
#define ROM_KM_KEY_MAX_SLOT_SPAN ROM_KM_KEY_SLOT_SPAN(ROM_KM_MAX_KEY_WORDS)

/** @brief Metadata for a single key handle. */
typedef struct {
    uint8_t base_slot;             /**< KPV base slot for this key */
    uint8_t key_words;             /**< Key length in 32-bit words (1-128) */
    uint8_t valid;                 /**< 1 if the handle is live, 0 if destroyed */
    rom_km_dest_bits_t dest_valid; /**< Permitted crypto-engine destination bitmask */
    uint32_t crc32;                /**< CRC-32 recorded at generation time */
} rom_km_keyreg_entry_t;

/** @brief Key handle registry (index 0 is unused / null handle). */
typedef struct {
    rom_km_keyreg_entry_t handles[ROM_KM_MAX_KEY_HANDLES + 1]; /**< Per-handle metadata */
    uint8_t slot_to_handle[ROM_KM_KPV_NUM_SLOTS];              /**< Reverse map: slot -> handle */
    uint8_t next_handle; /**< Next handle to allocate (starts at 1) */
} rom_km_keyreg_t;

/*===========================================================================
 * Initialization
 *===========================================================================*/

/**
 * @brief Initialize the key registry.
 *
 * Clears all handle entries and slot mappings, and sets the next
 * allocatable handle to 1.
 *
 * @param reg Registry to initialize.
 */
void rom_keyreg_init(rom_km_keyreg_t *reg);

/*===========================================================================
 * Lookup Functions
 *===========================================================================*/

/**
 * @brief Return the handle currently associated with a KPV slot.
 *
 * @param reg Registry to query.
 * @param slot KPV slot index (0 to ROM_KM_KPV_NUM_SLOTS-1).
 * @return Handle value, or 0 (ROM_KM_KEY_HANDLE_NULL) if no handle owns the slot.
 */
uint8_t rom_keyreg_get_handle(const rom_km_keyreg_t *reg, uint8_t slot);

/**
 * @brief Look up the base slot for a given handle.
 *
 * @param reg Registry to query.
 * @param handle Handle to look up (1-255).
 * @param slot Receives the base slot index.
 * @return 0 on success, -1 if the handle is invalid or destroyed.
 */
int rom_keyreg_get_slot(const rom_km_keyreg_t *reg, uint8_t handle, uint8_t *slot);

/**
 * @brief Look up the CRC-32 stored at generation time for a handle.
 *
 * @param reg Registry to query.
 * @param handle Handle to look up (1-255).
 * @param crc Receives the CRC-32 value.
 * @return 0 on success, -1 if the handle is invalid or destroyed.
 */
int rom_keyreg_get_crc(const rom_km_keyreg_t *reg, uint8_t handle, uint32_t *crc);

/**
 * @brief Look up the permitted crypto-engine destinations for a handle.
 *
 * @param reg Registry to query.
 * @param handle Handle to look up (1-255).
 * @param dest_valid Receives permitted destination bitmask.
 * @return 0 on success, -1 if the handle is invalid or destroyed.
 */
int rom_keyreg_get_dest_valid(const rom_km_keyreg_t *reg, uint8_t handle,
                              rom_km_dest_bits_t *dest_valid);

/**
 * @brief Look up a key's length in 32-bit words.
 *
 * @param reg Registry to query.
 * @param handle Handle to look up (1-255).
 * @param key_words Receives the key length in 32-bit words (1-128).
 * @return 0 on success, -1 if the handle is invalid or destroyed.
 */
int rom_keyreg_get_key_words(const rom_km_keyreg_t *reg, uint8_t handle, uint8_t *key_words);

/*===========================================================================
 * Allocation / Destruction
 *===========================================================================*/

/**
 * @brief Allocate a new handle for a freshly generated key.
 *
 * Assigns the next monotonic handle, records the base slot, key length, CRC,
 * and permitted destination mask, and updates the reverse slot-to-handle map
 * for every slot the key occupies.  The slot span is derived from
 * @p key_words, so the length is recorded once and cannot disagree with the
 * set of slots claimed for the key.
 *
 * @param reg Registry to update.
 * @param base_slot KPV base slot for the key.
 * @param key_words Key length in 32-bit words (1-128).
 * @param crc CRC-32 computed over the key material.
 * @param dest_valid Permitted crypto-engine destination bitmask.
 * @return Positive handle value (1-255) on success, -1 if @p key_words is
 *         outside 1-128, the key's span would run past the last KPV slot, or
 *         handles are exhausted.
 */
int rom_keyreg_generate(rom_km_keyreg_t *reg, uint8_t base_slot, uint8_t key_words, uint32_t crc,
                        rom_km_dest_bits_t dest_valid);

/**
 * @brief Destroy (invalidate) an existing handle.
 *
 * Marks the handle entry as invalid and clears all reverse-map entries
 * that point to this handle.
 *
 * @param reg Registry to update.
 * @param handle Handle to destroy (1-255).
 * @return 0 on success, -1 if the handle is invalid or already destroyed.
 */
int rom_keyreg_destroy(rom_km_keyreg_t *reg, uint8_t handle);

#endif /* ROM_KEYREG_H */
