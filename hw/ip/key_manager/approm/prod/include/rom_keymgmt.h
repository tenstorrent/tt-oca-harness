/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_keymgmt.h
 * @brief Key management operations for Key Manager firmware.
 *
 * High-level key lifecycle API: generation, integrity checking,
 * transfer to crypto engines, and revocation.
 */

#ifndef ROM_KEYMGMT_H
#define ROM_KEYMGMT_H

#include <stdint.h>
#include "rom_defs.h"

/**
 * @brief Verify the CRC integrity of a key stored in the KPV.
 *
 * Re-reads the key from the KPV, computes CRC-32C, and compares it
 * against the value recorded at generation time.  Triggers a
 * ROM_KM_RFAULT_KEY_SLOT_CRC recoverable fault on mismatch.
 *
 * @param handle Key handle (1-255).
 * @return 0 on success, -1 on invalid handle, -2 on CRC mismatch.
 */
int rom_check_key(uint8_t handle);

/**
 * @brief Generate a random key, store it in the KPV, and allocate a handle.
 *
 * Fills a local buffer from the DRBG and delegates to rom_load_key.
 *
 * @param key_size   Wire-encoded key length: actual word count minus 1 (0..127).
 * @param dest_valid Permitted destination engine bitmask (non-zero, ≤0xFF;
 *                   bits 0-3 = HMAC/KMAC/AES/OTBN, bits 4-7 = ABR seeds).
 * @param handle     Output: new 8-bit key handle on success.
 * @return 0 on success, -1 on invalid args or slot-fit failure,
 *         -2 on handle exhaustion, -3 on KPV write failure.
 */
int rom_generate_key(uint8_t key_size, rom_km_dest_bits_t dest_valid, uint8_t *handle);

/**
 * @brief Transfer a key from the KPV to one or more crypto engines.
 *
 * @param handle Key handle (1-255).
 * @param dest_engines Bitmask of target engines.
 * @return 0 on success, -1 on CRC failure, invalid handle, or
 *         destination permission violation.
 */
int rom_transfer_key(uint8_t handle, rom_km_dest_bits_t dest_engines);

/**
 * @brief Revoke a key by locking its KPV slots and destroying the handle.
 *
 * @param handle Key handle (1-255).
 * @return 0 on success, -1 if the handle is invalid.
 */
int rom_revoke_key(uint8_t handle);

/**
 * @brief Load caller-supplied key material into the KPV and allocate a handle.
 *
 * Allocates consecutive KPV slots (DRBG-randomized start; avoids write-locked
 * and handle-assigned slots), registers a handle before any KPV
 * mutation, shreds the selected slots, writes the key material, and
 * write-locks the slots.  On KPV write failure the registration is rolled back.
 *
 * Return codes:
 *   0  — success; *handle contains the new handle
 *  -1  — invalid args or slot-fit failure
 *  -2  — handle exhaustion (key registry is full; no KPV state was mutated)
 *  -3  — KPV write failure (handle registration rolled back)
 *
 * @param key_size   Wire-encoded key length: actual word count minus 1 (0..127).
 * @param dest_valid Permitted destination engine bitmask (non-zero, ≤0xFF;
 *                   bits 0-3 = HMAC/KMAC/AES/OTBN, bits 4-7 = ABR seeds).
 * @param key_data   Pointer to key_size+1 words of caller-supplied key material.
 * @param handle     Output: new 8-bit key handle on success.
 * @return 0 on success, -1 on invalid args or slot-fit failure,
 *         -2 on handle exhaustion, -3 on KPV write failure.
 */
int rom_load_key(uint8_t key_size, rom_km_dest_bits_t dest_valid, const uint32_t *key_data,
                 uint8_t *handle);

#endif /* ROM_KEYMGMT_H */
