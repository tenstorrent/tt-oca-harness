/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_keymgmt.c
 * @brief Key lifecycle operations for Key Manager firmware.
 *
 * Implements key generation, integrity checking, transfer, revocation,
 * and KPVLP slot allocation/registration helpers.
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
#include "rom_isr.h"
#include "key_manager_regs.h"

/*===========================================================================
 * Internal helpers
 *===========================================================================*/

/**
 * @brief Returns whether a KPV slot is allocatable.
 *
 * A slot is available only when it is unlocked, unassigned, and not
 * currently exposed to SEP via KPVLP.
 *
 * @param slot KPV slot index.
 * @return 1 if available, 0 otherwise.
 */
static int slot_available(uint8_t slot)
{
    if (slot >= ROM_KM_KPV_NUM_SLOTS)
        return 0;

    KM_KPV_CTRL_REG_reg_u ctrl;
    ctrl.val = KPV_CTRL(slot).val;

    if (ctrl.f.lock_write || ctrl.f.lock_use || ctrl.f.unlock_sep)
        return 0;

    if (rom_keyreg_get_handle(&rom_keyreg_state, slot) != ROM_KM_KEY_HANDLE_NULL)
        return 0;

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
static int find_consecutive_slots(uint8_t num_slots, uint8_t *base_slot)
{
    uint8_t start = (uint8_t)(rom_drbg_get_word() % ROM_KM_KPV_NUM_SLOTS);

    for (uint8_t tried = 0; tried < ROM_KM_KPV_NUM_SLOTS; tried++) {
        uint8_t candidate = (uint8_t)((start + tried) % ROM_KM_KPV_NUM_SLOTS);

        if (candidate + num_slots > ROM_KM_KPV_NUM_SLOTS)
            continue;

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

/*===========================================================================
 * rom_generate_key  (FR-0000-235)
 *===========================================================================*/

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
int rom_generate_key(uint8_t key_size, rom_km_dest_bits_t dest_valid, uint8_t *handle)
{
    uint32_t key_buf[key_size + 1];
    rom_drbg_get_block(key_buf, key_size + 1);
    return rom_load_key(key_size, dest_valid, key_buf, handle);
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
int rom_check_key(uint8_t handle)
{
    uint8_t base_slot;
    if (rom_keyreg_get_slot(&rom_keyreg_state, handle, &base_slot) < 0)
        return -1;

    uint32_t stored_crc;
    if (rom_keyreg_get_crc(&rom_keyreg_state, handle, &stored_crc) < 0)
        return -1;

    uint8_t key_len;
    rom_km_dest_bits_t dest_valid;
    if (rom_kpv_get_key_info(base_slot, &key_len, &dest_valid) < 0)
        return -1;

    uint32_t key_buf[key_len];
    if (rom_kpv_read_key(base_slot, key_buf, &key_len, &dest_valid) < 0)
        return -1;

    uint32_t computed_crc = rom_crc32c((const uint8_t *)key_buf, key_len * 4);
    if (computed_crc != stored_crc) {
        rom_trigger_recoverable(ROM_KM_RFAULT_KEY_SLOT_CRC);
        return -2;
    }

    return 0;
}

/*===========================================================================
 * rom_transfer_key  (FR-0000-238)
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
int rom_transfer_key(uint8_t handle, rom_km_dest_bits_t dest_engines)
{
    if (rom_check_key(handle) != 0)
        return -1;

    uint8_t base_slot;
    if (rom_keyreg_get_slot(&rom_keyreg_state, handle, &base_slot) < 0)
        return -1;

    uint8_t key_len;
    rom_km_dest_bits_t dest_valid;
    if (rom_kpv_get_key_info(base_slot, &key_len, &dest_valid) < 0)
        return -1;

    uint32_t key_buf[key_len];
    if (rom_kpv_read_key(base_slot, key_buf, &key_len, &dest_valid) < 0)
        return -1;

    if (dest_engines.raw & ~dest_valid.raw)
        return -1;

    if (dest_engines.hmac_sha2)
        rom_hmac_write_key(key_buf, key_len, &rom_prng_state);
    if (dest_engines.kmac_sha3)
        rom_kmac_write_key(key_buf, key_len, &rom_prng_state);
    if (dest_engines.aes)
        rom_aes_write_key(key_buf, key_len, &rom_prng_state);
    if (dest_engines.otbn)
        rom_otbn_write_key(key_buf, key_len, &rom_prng_state);

    return 0;
}

/*===========================================================================
 * rom_revoke_key  (FR-0000-237)
 *===========================================================================*/

/**
 * @brief Revoke a key by locking its KPV slots and destroying the handle.
 *
 * Write-locks and read-locks all slots so neither KM nor SEP can access
 * the data again, then removes the handle from the registry.  Slot
 * contents are not shredded (write-lock prevents further writes).
 *
 * @param handle Key handle.
 * @return 0 on success, -1 if the handle is invalid.
 */
int rom_revoke_key(uint8_t handle)
{
    uint8_t base_slot;
    if (rom_keyreg_get_slot(&rom_keyreg_state, handle, &base_slot) < 0)
        return -1;

    /* Program lock_use before lock_write; once write lock is set, subsequent
     * CTRL updates may be blocked by hardware policy. */
    rom_kpv_read_lock(base_slot);
    rom_kpv_write_lock(base_slot);

    if (rom_keyreg_destroy(&rom_keyreg_state, handle) < 0)
        return -1;

    return 0;
}

/*===========================================================================
 * rom_allocate_kpvlp_slot  (FR-0000-234)
 *===========================================================================*/

/**
 * @brief Allocate consecutive KPV slots for the SEP KPVLP load path.
 *
 * Finds a run of num_slots free consecutive slots from a DRBG-random
 * start, shreds them, and sets UNLOCK_SEP on each for SEP KPVLP writes.
 *
 * @param num_slots Number of consecutive slots to allocate.
 * @param base_slot Output base slot.
 * @return 0 on success, -1 if invalid args or no free run found.
 */
int rom_allocate_kpvlp_slot(uint8_t num_slots, uint8_t *base_slot)
{
    if (num_slots < 1 || num_slots > 8)
        return -1;

    uint8_t base;
    if (find_consecutive_slots(num_slots, &base) < 0)
        return -1;

    /* Shred each allocated slot before handing to SEP */
    for (uint8_t s = 0; s < num_slots; s++)
        rom_kpv_shred_slot(base + s, &rom_prng_state);

    /* Set UNLOCK_SEP to allow SEP writes through the KPVLP port */
    for (uint8_t s = 0; s < num_slots; s++) {
        KM_KPV_CTRL_REG_reg_u ctrl;
        ctrl.val = KPV_CTRL(base + s).val;
        ctrl.f.unlock_sep = 1;
        KPV_CTRL(base + s).val = ctrl.val;
    }

    *base_slot = base;
    return 0;
}

/*===========================================================================
 * rom_load_key  (FR-2739-013, FR-2739-014, FR-2739-020..023, FR-2739-030..031)
 *===========================================================================*/

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
                 const uint32_t *key_data, uint8_t *handle)
{
    if (key_size > 127u || dest_valid.raw == 0)
        return -1;

    uint8_t num_slots = (uint8_t)(key_size / ROM_KM_KPV_WORDS_PER_SLOT + 1);
    if (num_slots > 8)
        return -1;

    uint8_t base;
    if (find_consecutive_slots(num_slots, &base) < 0)
        return -1;

    /* CRC the SEP-supplied key data before writing to KPV (FR-2739-031). */
    uint32_t key_crc = rom_crc32c((const uint8_t *)key_data,
                                   (uint32_t)(key_size + 1u) * 4u);

    /* Register the handle before any KPV mutation (FR-2739-014); roll back on KPV failure. */
    int h = rom_keyreg_generate(&rom_keyreg_state, base, num_slots, key_crc);
    if (h < 0)
        return -2;

    /* Shred all selected slots before writing SEP-supplied data (FR-2739-021).
     * @verifies FR-2739-021 */
    for (uint8_t s = 0; s < num_slots; s++)
        rom_kpv_shred_slot(base + s, &rom_prng_state);

    /* Write key data and control fields (EXTEND, LAST_DWORD, DEST_VALID) (FR-2739-022). */
    if (rom_kpv_write_key(base, key_data, (uint8_t)(key_size + 1u), dest_valid) < 0) {
        rom_keyreg_destroy(&rom_keyreg_state, (uint8_t)h);
        return -3;
    }

    /* Write-lock all slots associated with this key (FR-2739-023). */
    rom_kpv_write_lock(base);

    *handle = (uint8_t)h;
    return 0;
}

/*===========================================================================
 * rom_register_kpvlp_key  (FR-0000-236)
 *===========================================================================*/

/**
 * @brief Register a key that was loaded through the KPVLP by the SEP.
 *
 * Verifies key integrity (CRC), write-locks the slots, performs
 * tamper-detection re-read, and allocates a handle.
 *
 * @param base_slot Base slot index from `rom_allocate_kpvlp_slot()`.
 * @param key_size Key length in 32-bit words.
 * @param dest_valid Allowed destination-engine mask.
 * @param crc SEP-computed CRC-32C over key words.
 * @param handle Output key handle.
 * @return 0 on success, -1 on error.
 */
int rom_register_kpvlp_key(uint8_t base_slot, uint8_t key_size,
                            rom_km_dest_bits_t dest_valid, uint32_t crc,
                            uint8_t *handle)
{
    if (key_size == 0 || dest_valid.raw == 0)
        return -1;

    uint8_t num_slots = (uint8_t)((key_size - 1) / ROM_KM_KPV_WORDS_PER_SLOT + 1);

    if (base_slot + num_slots > ROM_KM_KPV_NUM_SLOTS)
        return -1;

    /* Validate each slot: must be SEP-allocated (unlock_sep), not locked,
     * and must not already have a handle. */
    for (uint8_t s = 0; s < num_slots; s++) {
        uint8_t slot = base_slot + s;
        KM_KPV_CTRL_REG_reg_u ctrl;
        ctrl.val = KPV_CTRL(slot).val;

        if (!ctrl.f.unlock_sep)
            return -1;
        if (ctrl.f.lock_write || ctrl.f.lock_use)
            return -1;
        if (rom_keyreg_get_handle(&rom_keyreg_state, slot) != ROM_KM_KEY_HANDLE_NULL)
            return -1;
    }

    uint8_t read_len;
    rom_km_dest_bits_t read_dest;
    if (rom_kpv_get_key_info(base_slot, &read_len, &read_dest) < 0)
        return -1;

    /* Verify key_size and dest_valid match what the KPV control says.
     * The SEP should have configured EXTEND/LAST_DWORD/DEST_VALID via
     * the KPVLP port before calling register. */
    if (read_len != key_size)
        return -1;
    if (read_dest.raw != dest_valid.raw)
        return -1;

    /* CRC integrity check: compare SEP-provided CRC with computed. */
    uint32_t temp_key[key_size];
    if (rom_kpv_read_key(base_slot, temp_key, &read_len, &read_dest) < 0)
        return -1;

    uint32_t computed_crc = rom_crc32c((const uint8_t *)temp_key,
                                        (uint32_t)key_size * 4);
    if (computed_crc != crc)
        return -1;

    /* Write-lock the slots to prevent further modification. */
    rom_kpv_write_lock(base_slot);

    uint32_t verify_key[key_size];
    uint8_t verify_len;
    rom_km_dest_bits_t verify_dest;
    if (rom_kpv_read_key(base_slot, verify_key, &verify_len, &verify_dest) < 0)
        return -1;

    uint32_t verify_crc = rom_crc32c((const uint8_t *)verify_key,
                                      (uint32_t)verify_len * 4);
    if (verify_crc != computed_crc)
        return -1;

    /* Allocate a handle for the registered key. */
    int h = rom_keyreg_generate(&rom_keyreg_state, base_slot, num_slots, crc);
    if (h < 0)
        return -1;

    *handle = (uint8_t)h;
    return 0;
}
