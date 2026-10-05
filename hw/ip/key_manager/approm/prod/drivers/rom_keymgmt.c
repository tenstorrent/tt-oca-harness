/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_keymgmt.c
 * @brief Key lifecycle operations for Key Manager firmware.
 *
 * Implements key generation, integrity checking, transfer, and revocation.
 */

#include "rom_defs.h"
#include "rom_state.h"
#include "rom_keymgmt.h"
#include "rom_kpv.h"
#include "rom_keyreg.h"
#include "rom_crc.h"
#include "rom_drbg.h"
#include "rom_prng.h"
#include "rom_sideload.h"
#include "rom_secutil.h"
#include "rom_isr.h"
#include "key_manager_fw.h"

/*===========================================================================
 * Internal helpers
 *===========================================================================*/

/**
 * @brief Returns whether a KPV slot is allocatable.
 *
 * A slot is available only when it is unlocked and unassigned.
 *
 * @param slot KPV slot index.
 * @return 1 if available, 0 otherwise.
 */
static int slot_available(uint8_t slot) {
    if (slot >= ROM_KM_KPV_NUM_SLOTS) return 0;

    km_kpv__ctrl_reg_t ctrl;
    ctrl.w = KPV_CTRL(slot).w;

    if (ctrl.f.lock_write || ctrl.f.lock_use) return 0;

    if (rom_keyreg_get_handle(&rom_keyreg_state, slot) != ROM_KM_KEY_HANDLE_NULL) return 0;

    return 1;
}

/**
 * @brief Finds a consecutive free slot run.
 *
 * Search starts from a DRBG-random index and wraps once around KPV.
 *
 * @param num_slots Number of consecutive slots required.
 * @param base_slot Output base slot on success.
 * @return 0 on success, -1 if no run of the required length exists.
 */
static int find_consecutive_slots(uint8_t num_slots, uint8_t *base_slot) {
    uint8_t start = (uint8_t)(rom_drbg_get_word() % ROM_KM_KPV_NUM_SLOTS);

    for (uint8_t tried = 0; tried < ROM_KM_KPV_NUM_SLOTS; tried++) {
        uint8_t candidate = (uint8_t)((start + tried) % ROM_KM_KPV_NUM_SLOTS);

        if (candidate + num_slots > ROM_KM_KPV_NUM_SLOTS) continue;

        uint8_t ok = 1;
        for (uint8_t s = 0; s < num_slots; s++) {
            if (!slot_available(candidate + s)) {
                ok = 0;
                break;
            }
        }

        if (ok) {
            *base_slot = candidate;
            return 0;
        }
    }

    return -1;
}

/**
 * @brief Copies a key out of the KPV slots that hold it.
 *
 * The KPV works one slot at a time and masks nothing, so the extent comes
 * from the caller (ultimately the key registry) and the final slot is read
 * short rather than in full.
 *
 * @param base_slot First slot of the key.
 * @param key_words Key length in 32-bit words.
 * @param key_buf   Output buffer of at least key_words words.
 * @return 0 on success, -1 if any of the key's slots is read-locked.
 */
static int read_key_slots(uint8_t base_slot, uint8_t key_words, uint32_t *key_buf) {
    uint8_t num_slots = ROM_KM_KEY_SLOT_SPAN(key_words);
    uint8_t words_read = 0;

    for (uint8_t s = 0; s < num_slots; s++) {
        uint8_t remaining = (uint8_t)(key_words - words_read);
        uint8_t n = (remaining < ROM_KM_KPV_WORDS_PER_SLOT) ? remaining
                                                            : (uint8_t)ROM_KM_KPV_WORDS_PER_SLOT;

        if (rom_kpv_read_slot((uint8_t)(base_slot + s), &key_buf[words_read], n) < 0) return -1;

        words_read = (uint8_t)(words_read + n);
    }

    return 0;
}

/*===========================================================================
 * rom_generate_key
 *===========================================================================*/

/**
 * @brief Generate a random key, store it in the KPV, and allocate a handle.
 *
 * Fills a local buffer from the DRBG and delegates to rom_load_key.
 *
 * @param key_size   Wire-encoded key length: actual word count minus 1 (0..127).
 * @param dest_valid Permitted destination engine bitmask (non-zero, ≤0xFF).
 * @param handle     Output: new 8-bit key handle on success.
 * @return 0 on success, -1 on invalid args or slot-fit failure,
 *         -2 on handle exhaustion, -3 on KPV write failure.
 */
int rom_generate_key(uint8_t key_size, rom_km_dest_bits_t dest_valid, uint8_t *handle) {
    if (key_size > 127u) return -1;

    uint32_t key_buf[ROM_KM_MAX_KEY_WORDS];
    rom_drbg_get_block(key_buf, key_size + 1);
    int rc = rom_load_key(key_size, dest_valid, key_buf, handle);
    /* Only the first key_size+1 words ever held key material. */
    rom_secure_memzero(key_buf, (size_t)(key_size + 1u) * sizeof(key_buf[0]));
    return rc;
}

/*===========================================================================
 * rom_check_key
 *===========================================================================*/

/**
 * @brief Verifies key integrity against stored CRC.
 *
 * @param handle Key handle.
 * @return 0 if CRC matches, -1 on error, -2 on CRC mismatch.
 */
int rom_check_key(uint8_t handle) {
    uint8_t base_slot;
    if (rom_keyreg_get_slot(&rom_keyreg_state, handle, &base_slot) < 0) return -1;

    uint32_t stored_crc;
    if (rom_keyreg_get_crc(&rom_keyreg_state, handle, &stored_crc) < 0) return -1;

    uint8_t key_len;
    if (rom_keyreg_get_key_words(&rom_keyreg_state, handle, &key_len) < 0) return -1;

    if (key_len > ROM_KM_MAX_KEY_WORDS) return -1;

    uint32_t key_buf[ROM_KM_MAX_KEY_WORDS];
    if (read_key_slots(base_slot, key_len, key_buf) < 0) {
        rom_secure_memzero(key_buf, (size_t)key_len * sizeof(key_buf[0]));
        return -1;
    }

    uint32_t computed_crc = rom_crc32c((const uint8_t *)key_buf, key_len * 4);
    rom_secure_memzero(key_buf, (size_t)key_len * sizeof(key_buf[0]));

    /* Constant-time, glitch-aware compare so a fault that skips the integrity
     * check is detected (rom_const_time_memcmp returns non-zero on mismatch). */
    if (rom_const_time_memcmp(&computed_crc, &stored_crc, sizeof(computed_crc)) != 0) {
        rom_trigger_recoverable(ROM_KM_RFAULT_KEY_SLOT_CRC);
        return -2;
    }

    return 0;
}

/*===========================================================================
 * rom_transfer_key
 *===========================================================================*/

/**
 * @brief Transfer a key from the KPV to one or more crypto engines.
 *
 * Performs CRC integrity check, then verifies dest_engines against the
 * key's dest_valid mask.  On success, writes the key into each selected
 * engine.
 *
 * @param handle Key handle.
 * @param dest_engines Bitmask of destination engines.
 * @return 0 on success, -1 on CRC failure, invalid handle, or
 *         destination permission violation.
 */
int rom_transfer_key(uint8_t handle, rom_km_dest_bits_t dest_engines) {
    if (rom_check_key(handle) != 0) return -1;

    uint8_t base_slot;
    if (rom_keyreg_get_slot(&rom_keyreg_state, handle, &base_slot) < 0) return -1;

    uint8_t key_len;
    rom_km_dest_bits_t dest_valid;
    if (rom_keyreg_get_dest_valid(&rom_keyreg_state, handle, &dest_valid) < 0) return -1;

    if (rom_keyreg_get_key_words(&rom_keyreg_state, handle, &key_len) < 0) return -1;

    if (key_len > ROM_KM_MAX_KEY_WORDS) return -1;

    uint32_t key_buf[ROM_KM_MAX_KEY_WORDS];
    if (read_key_slots(base_slot, key_len, key_buf) < 0) {
        rom_secure_memzero(key_buf, (size_t)key_len * sizeof(key_buf[0]));
        return -1;
    }

    /* Single exit so the plaintext key in key_buf is wiped on every path.
     * The chain stops at the first failure (a requested engine is written
     * only after the previous one succeeds). */
    int rc = 0;
    if (dest_engines.raw & ~dest_valid.raw)
        rc = -1;
    else if (dest_engines.hmac_sha2 && rom_hmac_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.kmac_sha3 && rom_kmac_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.aes && rom_aes_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.otbn && rom_otbn_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.abr_mldsa_seed &&
             rom_abr_mldsa_seed_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.abr_mlkem_seed_d &&
             rom_abr_mlkem_seed_d_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.abr_mlkem_seed_z &&
             rom_abr_mlkem_seed_z_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;
    else if (dest_engines.abr_mlkem_msg &&
             rom_abr_mlkem_msg_write_key(key_buf, key_len, &rom_prng_state) < 0)
        rc = -1;

    rom_secure_memzero(key_buf, (size_t)key_len * sizeof(key_buf[0]));
    return rc;
}

/*===========================================================================
 * rom_revoke_key
 *===========================================================================*/

/**
 * @brief Revoke a key by hardware-erasing its KPV slots and destroying the handle.
 *
 * Triggers the hardware erase on every slot spanned by the key, which
 * overwrites the key data with LFSR/scrambler output and clears each slot's
 * CTRL register (including the lock bits). Erase is not blocked by the slot
 * locks, and rom_kpv_erase_slot blocks until it completes, so the slots are
 * wiped and reusable before the handle is removed from the registry.
 *
 * @param handle Key handle.
 * @return 0 on success, -1 if the handle is invalid.
 */
int rom_revoke_key(uint8_t handle) {
    uint8_t base_slot;
    if (rom_keyreg_get_slot(&rom_keyreg_state, handle, &base_slot) < 0) return -1;

    uint8_t key_words;
    if (rom_keyreg_get_key_words(&rom_keyreg_state, handle, &key_words) < 0) return -1;

    /* Erase the slots in hardware (data overwrite + CTRL/lock clear); blocks
     * until each slot's erase bit self-clears, freeing the slots for reuse. */
    uint8_t num_slots = ROM_KM_KEY_SLOT_SPAN(key_words);
    for (uint8_t s = 0; s < num_slots; s++) rom_kpv_erase_slot((uint8_t)(base_slot + s));

    if (rom_keyreg_destroy(&rom_keyreg_state, handle) < 0) return -1;

    return 0;
}

/*===========================================================================
 * rom_load_key
 *===========================================================================*/

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
 * @param dest_valid Permitted destination engine bitmask (non-zero, ≤0xFF).
 * @param key_data   Pointer to key_size+1 words of caller-supplied key material.
 * @param handle     Output: new 8-bit key handle on success.
 * @return 0 on success, -1 on invalid args or slot-fit failure,
 *         -2 on handle exhaustion, -3 on KPV write failure.
 */
int rom_load_key(uint8_t key_size, rom_km_dest_bits_t dest_valid, const uint32_t *key_data,
                 uint8_t *handle) {
    if (key_size > 127u || dest_valid.raw == 0) return -1;

    uint8_t key_words = (uint8_t)(key_size + 1u);
    uint8_t num_slots = ROM_KM_KEY_SLOT_SPAN(key_words);
    if (num_slots > ROM_KM_KEY_MAX_SLOT_SPAN) return -1;

    uint8_t base;
    if (find_consecutive_slots(num_slots, &base) < 0) return -1;

    /* CRC the SEP-supplied key data before writing to KPV. */
    uint32_t key_crc = rom_crc32c((const uint8_t *)key_data, (uint32_t)key_words * 4u);

    /* Register the handle before any KPV mutation; roll back on KPV failure.
     * The registry records the key length, which is the only record of it. */
    int h = rom_keyreg_generate(&rom_keyreg_state, base, key_words, key_crc, dest_valid);
    if (h < 0) return -2;

    /* Shred all selected slots before writing SEP-supplied data. */
    for (uint8_t s = 0; s < num_slots; s++) rom_kpv_shred_slot((uint8_t)(base + s));

    /* Write the key material a slot at a time; the final slot takes only the
     * words that remain. */
    uint8_t words_written = 0;
    for (uint8_t s = 0; s < num_slots; s++) {
        uint8_t remaining = (uint8_t)(key_words - words_written);
        uint8_t n = (remaining < ROM_KM_KPV_WORDS_PER_SLOT) ? remaining
                                                            : (uint8_t)ROM_KM_KPV_WORDS_PER_SLOT;

        if (rom_kpv_write_slot((uint8_t)(base + s), &key_data[words_written], n) < 0) {
            rom_keyreg_destroy(&rom_keyreg_state, (uint8_t)h);
            return -3;
        }

        words_written = (uint8_t)(words_written + n);
    }

    /* Write-lock all slots associated with this key. */
    for (uint8_t s = 0; s < num_slots; s++) rom_kpv_write_lock((uint8_t)(base + s));

    *handle = (uint8_t)h;
    return 0;
}
