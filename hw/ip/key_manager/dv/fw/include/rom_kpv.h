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
 *
 * Every entry point here works on exactly one slot and knows nothing of keys:
 * the KPV stores key data and lock state only, so a key's slot span and its
 * final-slot word count are software state held in the key registry
 * (rom_keyreg).  Callers that operate on a whole key loop over its slots.
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
 * @param slot Slot index (0-31).
 */
void rom_kpv_shred_slot(uint8_t slot);

/**
 * @brief Hardware-erase one slot, then wait for it to complete.
 *
 * Asserts the slot's CTRL.erase trigger, then busy-waits for the hardware to
 * overwrite the slot's key words with LFSR data (through the KPV scrambler)
 * and clear its CTRL register (including lock_write/lock_use), clearing the
 * erase bit on completion. Erase is not blocked by the slot locks. This
 * function blocks until the erase bit has self-cleared, after which the slot
 * is reusable.
 *
 * @param[in] slot Slot index (0-31).
 */
void rom_kpv_erase_slot(uint8_t slot);

/*===========================================================================
 * Key Data Functions
 *===========================================================================*/

/**
 * @brief Write key words into one KPV slot.
 *
 * Writes @p n_words words starting at word 0 of the slot; any remaining words
 * of the slot are left holding whatever the preceding shred put there.
 * Returns an error without writing anything if the slot is write-locked.
 *
 * @param slot Slot index (0-31).
 * @param words Key data (@p n_words 32-bit words).
 * @param n_words Words to write (1-16).
 * @return 0 on success, -1 if @p n_words is outside 1-16 or the slot is
 *         write-locked.
 */
int rom_kpv_write_slot(uint8_t slot, const uint32_t *words, uint8_t n_words);

/**
 * @brief Read key words out of one KPV slot.
 *
 * Reads @p n_words words starting at word 0 of the slot.  How many words are
 * meaningful is the caller's business: the hardware masks nothing, so words
 * past a key's length read back as the shred's LFSR data rather than zero.
 *
 * @param slot Slot index (0-31).
 * @param words Buffer for @p n_words 32-bit words.
 * @param n_words Words to read (1-16).
 * @return 0 on success, -1 if @p n_words is outside 1-16 or the slot is
 *         read-locked.
 */
int rom_kpv_read_slot(uint8_t slot, uint32_t *words, uint8_t n_words);

/*===========================================================================
 * Lock Functions
 *===========================================================================*/

/**
 * @brief Write-lock one slot, with triple write.
 *
 * The register write is issued three times so a single skipped store (e.g.
 * from a fault-injection glitch) cannot leave the slot writable.
 *
 * @param slot Slot index (0-31).
 */
void rom_kpv_write_lock(uint8_t slot);

/**
 * @brief Read-lock (lock_use) one slot, with triple write.
 *
 * The register write is issued three times so a single skipped store (e.g.
 * from a fault-injection glitch) cannot leave the key readable.
 *
 * @param slot Slot index (0-31).
 */
void rom_kpv_read_lock(uint8_t slot);

#endif /* ROM_KPV_H */
