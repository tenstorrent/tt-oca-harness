/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_keymgmt.h
 * @brief Key management operations for Key Manager firmware.
 *
 * High-level key lifecycle API: generation, integrity checking,
 * transfer to crypto engines, revocation, and KPVLP slot allocation
 * and key registration.
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
 * @param dest_valid Permitted destination engine bitmask (non-zero, ≤0x0F).
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
 * @brief Allocate consecutive KPV slots for the SEP KPVLP load path.
 *
 * @param num_slots Number of consecutive slots to allocate (1-8).
 * @param base_slot Output base slot index.
 * @return 0 on success, -1 if invalid args or no free run found.
 */
int rom_allocate_kpvlp_slot(uint8_t num_slots, uint8_t *base_slot);

/**
 * @brief Register a key loaded through the KPVLP by the SEP.
 *
 * Verifies key integrity via CRC, write-locks the slots, performs a
 * tamper-detection re-read, and allocates a handle.
 *
 * @param base_slot Base slot index (from `rom_allocate_kpvlp_slot()`).
 * @param key_size Key length in 32-bit words.
 * @param dest_valid Permitted crypto-engine destination bitmask.
 * @param crc CRC-32C computed by SEP over key words.
 * @param handle Output key handle.
 * @return 0 on success, -1 on error.
 */
int rom_register_kpvlp_key(uint8_t base_slot, uint8_t key_size,
                            rom_km_dest_bits_t dest_valid, uint32_t crc,
                            uint8_t *handle);

/**
 * @brief Load caller-supplied key material into the KPV and allocate a handle.
 *
 * Allocates consecutive KPV slots (DRBG-randomized start; avoids UNLOCK_SEP=1,
 * write-locked, and handle-assigned slots), registers a handle before any KPV
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
 * @param dest_valid Permitted destination engine bitmask (non-zero, ≤0x0F).
 * @param key_data   Pointer to key_size+1 words of caller-supplied key material.
 * @param handle     Output: new 8-bit key handle on success.
 * @return 0 on success, -1 on invalid args or slot-fit failure,
 *         -2 on handle exhaustion, -3 on KPV write failure.
 */
int rom_load_key(uint8_t key_size, rom_km_dest_bits_t dest_valid,
                 const uint32_t *key_data, uint8_t *handle);

#endif /* ROM_KEYMGMT_H */
