/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kpv.h
 * @brief Key Provisioning Vault (KPV) driver for Key Manager firmware
 *
 * Provides scrambler initialization/control, slot shredding, key read/write,
 * and write/read locking through the PeakRDL-generated register unions in
 * key_manager.h / key_manager_addr.h.
 */

#ifndef ROM_KPV_H
#define ROM_KPV_H

#include <stdint.h>
#include "rom_defs.h"
#include "key_manager_fw.h"

/*===========================================================================
 * Indexed Register Access Macros
 *===========================================================================*/

/** @brief Access KPV key data word [word] in slot [slot]. */
#define KPV_KEY_WORD(slot, word) \
    (*(volatile uint32_t *)(KEY_MANAGER_KPV_KEY_ENTRY_WORD_BASE_ADDR(0, 0) + (slot)*0x40 + \
                            (word)*4))

/** @brief Access KPV control register for slot [slot]. */
#define KPV_CTRL(slot) \
    (*(volatile km_kpv__ctrl_reg_t *)(KEY_MANAGER_KPV_CTRL_BASE_ADDR(0) + (slot)*4))

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
 * @brief Shred all KPV slots via the hardware erase path.
 *
 * Calls rom_kpv_shred_slot on every slot, erasing each slot SHRED_ITER+1
 * times.  Each erase overwrites the slot data with LFSR output (through the
 * KPV scrambler) and clears the slot CTRL register, so write-locked slots are
 * wiped too.
 */
void rom_kpv_shred_all(void);

/**
 * @brief Shred a single KPV slot via the hardware erase path.
 *
 * Calls rom_kpv_erase_slot on the slot SHRED_ITER+1 times.  Each erase
 * overwrites the slot data with LFSR output (through the KPV scrambler) and
 * clears the slot CTRL register, so a write-locked slot is wiped too.
 *
 * @param slot Slot index (0-31); EXTEND determines the span erased.
 */
void rom_kpv_shred_slot(uint8_t slot);

/**
 * @brief Hardware-erase the base slot and all extended slots, then wait.
 *
 * Asserts the per-slot CTRL.erase trigger on every slot spanned by the key
 * (base slot EXTEND field determines the span), then busy-waits for the
 * hardware to overwrite each slot's key words with LFSR data (through the
 * KPV scrambler) and clear its CTRL register (including lock_write/lock_use),
 * clearing the erase bit on completion. Erase is not blocked by the slot
 * locks. This function blocks until every slot's erase bit has self-cleared,
 * after which the slots are reusable.
 *
 * @param[in] base_slot First slot index (EXTEND field determines the span).
 */
void rom_kpv_erase_slot(uint8_t base_slot);

/*===========================================================================
 * Key Data Functions
 *===========================================================================*/

/**
 * @brief Write key data and control fields to the KPV.
 *
 * Computes EXTEND = (key_len-1)/16, sets LAST_DWORD on each required slot,
 * and writes the key words.  Returns an error if any required slot is
 * write-locked (no data is written in that case).  The permitted-destination
 * mask is tracked in the software key registry (rom_keyreg), not in KPV CTRL.
 *
 * @param base_slot Base slot index (0-31).
 * @param key Key data (key_len 32-bit words).
 * @param key_len Key length in 32-bit words (1-128).
 * @return 0 on success, -1 on error.
 */
int rom_kpv_write_key(uint8_t base_slot, const uint32_t *key, uint8_t key_len);

/**
 * @brief Get key length from KPV control registers (no key data read).
 *
 * Same validation as rom_kpv_read_key (lock_use, last_dword).
 *
 * @param base_slot Base slot index (0-31).
 * @param key_len Receives total key length in 32-bit words.
 * @return 0 on success, -1 if any slot is read-locked or control fields malformed.
 */
int rom_kpv_get_key_info(uint8_t base_slot, uint8_t *key_len);

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
 * @return 0 on success, -1 on error.
 */
int rom_kpv_read_key(uint8_t base_slot, uint32_t *key, uint8_t *key_len);

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
