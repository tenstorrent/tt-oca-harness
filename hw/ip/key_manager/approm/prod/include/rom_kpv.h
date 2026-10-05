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
 * wiped too.  A sealed slot is erased as well, but comes out retired rather
 * than free: its data is destroyed and the slot cannot be reused.
 */
void rom_kpv_shred_all(void);

/**
 * @brief Shred a single KPV slot via the hardware erase path.
 *
 * Calls rom_kpv_erase_slot on the slot SHRED_ITER+1 times.  Each erase
 * overwrites the slot data with LFSR output (through the KPV scrambler) and
 * clears the slot CTRL register, so a write-locked slot is wiped too.  A
 * sealed slot ends up retired instead of free.
 *
 * @param slot Slot index (0-63).
 */
void rom_kpv_shred_slot(uint8_t slot);

/**
 * @brief Hardware-erase one slot, then wait for it to complete.
 *
 * Asserts the slot's CTRL.erase trigger, then busy-waits for the hardware to
 * overwrite the slot's key words with LFSR data (through the KPV scrambler),
 * which clears the erase bit on completion.  Erase is never blocked: no lock
 * bit and no seal prevents it.  The slot's seal state decides what the slot
 * looks like afterwards.  Unsealed, its CTRL register is cleared and the slot
 * is reusable.  Sealed, the slot is retired: lock_write stays set, lock_use is
 * set, and the slot can be neither read, rewritten nor reused until warm
 * reset.
 *
 * @param[in] slot Slot index (0-63).
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
 * @param slot Slot index (0-63).
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
 * @param slot Slot index (0-63).
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
 * @param slot Slot index (0-63).
 */
void rom_kpv_write_lock(uint8_t slot);

/**
 * @brief Read-lock (lock_use) one slot, with triple write.
 *
 * The register write is issued three times so a single skipped store (e.g.
 * from a fault-injection glitch) cannot leave the key readable.
 *
 * @param slot Slot index (0-63).
 */
void rom_kpv_read_lock(uint8_t slot);

/**
 * @brief Seal one slot, with triple write.
 *
 * A sealed slot's data can be read but not overwritten until the next warm
 * reset.  It can still be erased, which retires the slot rather than freeing
 * it, so sealing a slot commits its slot as well as its contents: the material
 * can be revoked but the slot never carries anything else.
 *
 * Only the seal bit is written; hardware sets lock_write alongside it.
 *
 * @param slot Slot index (0-63).
 * @return 0 when the seal and the hardware-set write lock both read back set,
 *         -1 otherwise.
 */
int rom_kpv_seal_slot(uint8_t slot);

/**
 * @brief Report whether one slot is sealed.
 *
 * The check a consumer of surviving key material makes before trusting it: a
 * sealed slot cannot have been altered since the seal was taken, because
 * lock_write blocks writes and a seal holds lock_write set.  True of a retired
 * slot too, whose material is gone: pair with rom_kpv_slot_retired() to tell
 * the two apart.
 *
 * @param slot Slot index (0-63).
 * @return 1 if both lock_write and seal are set, 0 otherwise.
 */
int rom_kpv_slot_sealed(uint8_t slot);

/**
 * @brief Report whether one slot is retired.
 *
 * A retired slot is a sealed slot that has been erased: its data is destroyed
 * and it can be neither read nor reused until warm reset.  A sealed slot gains
 * lock_use only from an erase completing, so a set lock_use is what separates a
 * retired slot from a sealed live one.
 *
 * @param slot Slot index (0-63).
 * @return 1 if both seal and lock_use are set, 0 otherwise.
 */
int rom_kpv_slot_retired(uint8_t slot);

#endif /* ROM_KPV_H */
