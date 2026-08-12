/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_keyreg.c
 * @brief Key handle registry implementation
 *
 * Monotonic handle allocation with reverse slot-to-handle mapping.
 * Handle 0 is reserved (null); valid handles are 1-255.
 */

#include "rom_keyreg.h"
#include "rom_defs.h"

/*===========================================================================
 * Initialization
 *===========================================================================*/

/**
 * @brief Initialize the key handle registry to empty state.
 *
 * @param[in,out] reg Registry to initialize.
 */
void rom_keyreg_init(rom_km_keyreg_t *reg) {
    for (uint16_t i = 0; i < ROM_KM_MAX_KEY_HANDLES + 1; i++) {
        reg->handles[i].base_slot = 0;
        reg->handles[i].key_words = 0;
        reg->handles[i].valid = 0;
        reg->handles[i].dest_valid.raw = 0;
        reg->handles[i].crc32 = 0;
    }

    for (uint8_t s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++)
        reg->slot_to_handle[s] = ROM_KM_KEY_HANDLE_NULL;

    reg->next_handle = 1;
}

/*===========================================================================
 * Lookup Functions
 *===========================================================================*/

/**
 * @brief Get the key handle associated with a slot, if any.
 *
 * @param[in] reg  Registry.
 * @param[in] slot Slot index.
 * @return Handle (1-255) or ROM_KM_KEY_HANDLE_NULL if no key in slot.
 */
uint8_t rom_keyreg_get_handle(const rom_km_keyreg_t *reg, uint8_t slot) {
    if (slot >= ROM_KM_KPV_NUM_SLOTS) return ROM_KM_KEY_HANDLE_NULL;

    return reg->slot_to_handle[slot];
}

/**
 * @brief Get the base slot for a key handle.
 *
 * @param[in]  reg   Registry.
 * @param[in]  handle Key handle.
 * @param[out] slot  Receives base slot index.
 * @return 0 on success, -1 if handle invalid.
 */
int rom_keyreg_get_slot(const rom_km_keyreg_t *reg, uint8_t handle, uint8_t *slot) {
    if (handle == ROM_KM_KEY_HANDLE_NULL || !reg->handles[handle].valid) return -1;

    *slot = reg->handles[handle].base_slot;
    return 0;
}

/**
 * @brief Get the stored CRC-32C for a key handle.
 *
 * @param[in]  reg   Registry.
 * @param[in]  handle Key handle.
 * @param[out] crc   Receives CRC value.
 * @return 0 on success, -1 if handle invalid.
 */
int rom_keyreg_get_crc(const rom_km_keyreg_t *reg, uint8_t handle, uint32_t *crc) {
    if (handle == ROM_KM_KEY_HANDLE_NULL || !reg->handles[handle].valid) return -1;

    *crc = reg->handles[handle].crc32;
    return 0;
}

/**
 * @brief Look up the permitted crypto-engine destinations for a handle.
 *
 * @param[in]  reg        Registry.
 * @param[in]  handle     Key handle.
 * @param[out] dest_valid Receives permitted destination bitmask.
 * @return 0 on success, -1 if handle invalid.
 */
int rom_keyreg_get_dest_valid(const rom_km_keyreg_t *reg, uint8_t handle,
                              rom_km_dest_bits_t *dest_valid) {
    if (handle == ROM_KM_KEY_HANDLE_NULL || !reg->handles[handle].valid) return -1;

    *dest_valid = reg->handles[handle].dest_valid;
    return 0;
}

/**
 * @brief Get a key's length in 32-bit words.
 *
 * @param[in]  reg       Registry.
 * @param[in]  handle    Key handle.
 * @param[out] key_words Receives key length in words.
 * @return 0 on success, -1 if handle invalid.
 */
int rom_keyreg_get_key_words(const rom_km_keyreg_t *reg, uint8_t handle, uint8_t *key_words) {
    if (handle == ROM_KM_KEY_HANDLE_NULL || !reg->handles[handle].valid) return -1;

    *key_words = reg->handles[handle].key_words;
    return 0;
}

/*===========================================================================
 * Allocation / Destruction
 *===========================================================================*/

/**
 * @brief Allocate a new handle and associate it with slots, length, and CRC.
 *
 * @param[in,out] reg       Registry.
 * @param[in]     base_slot Base slot index.
 * @param[in]     key_words Key length in 32-bit words.
 * @param[in]     crc       CRC-32C of key data.
 * @return Allocated handle (1-255) on success, -1 if the extent is invalid,
 *         the key does not fit at @p base_slot, or handles are exhausted.
 */
int rom_keyreg_generate(rom_km_keyreg_t *reg, uint8_t base_slot, uint8_t key_words, uint32_t crc,
                        rom_km_dest_bits_t dest_valid) {
    /* The registry is the only record of a key's extent, so reject a length it
     * could not describe: zero spans no slots yet would still yield a live
     * handle. Widened because base_slot + span can exceed a uint8_t. */
    if (key_words == 0 || key_words > ROM_KM_MAX_KEY_WORDS) return -1;

    uint8_t num_slots = ROM_KM_KEY_SLOT_SPAN(key_words);
    if ((uint16_t)base_slot + num_slots > ROM_KM_KPV_NUM_SLOTS) return -1;

    if (reg->next_handle == 0) return -1;

    uint8_t h = reg->next_handle;

    reg->handles[h].base_slot = base_slot;
    reg->handles[h].key_words = key_words;
    reg->handles[h].valid = 1;
    reg->handles[h].dest_valid = dest_valid;
    reg->handles[h].crc32 = crc;

    for (uint8_t s = 0; s < num_slots; s++) reg->slot_to_handle[base_slot + s] = h;

    reg->next_handle++;

    return (int)h;
}

/**
 * @brief Destroy a handle and clear slot-to-handle mapping.
 *
 * @param[in,out] reg    Registry.
 * @param[in]     handle Handle to destroy.
 * @return 0 on success, -1 if handle invalid.
 */
int rom_keyreg_destroy(rom_km_keyreg_t *reg, uint8_t handle) {
    if (handle == ROM_KM_KEY_HANDLE_NULL || !reg->handles[handle].valid) return -1;

    reg->handles[handle].valid = 0;
    reg->handles[handle].dest_valid.raw = 0;

    for (uint8_t s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        if (reg->slot_to_handle[s] == handle) reg->slot_to_handle[s] = ROM_KM_KEY_HANDLE_NULL;
    }

    return 0;
}
