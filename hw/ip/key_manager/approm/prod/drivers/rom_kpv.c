/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kpv.c
 * @brief Key Provisioning Vault (KPV) driver implementation
 *
 * Scrambler control, slot shredding (single and bulk), key read/write, and
 * lock operations.  Shredding drives the hardware erase path, which overwrites
 * each slot through the KPV scrambler and clears its control register, so
 * write-locked slots are wiped too.  A sealed slot is erased like any other,
 * but ends up retired rather than free.
 */

#include "rom_kpv.h"
#include "rom_defs.h"
#include "rom_drbg.h"
#include "key_manager_fw.h"

/** @brief KPV scrambler key register (volatile, write-only). */
#define KPV_SCRAMBLER_KEY \
    (*(volatile km_kpv__kpv_scrambler_key_reg_t *)KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR)
/** @brief KPV scrambler control register (volatile, R/W). */
#define KPV_SCRAMBLER_CTRL \
    (*(volatile km_kpv__kpv_scrambler_ctrl_reg_t *)KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR)

/** @brief Base of KPV key array (ROM_KM_KPV_NUM_SLOTS × 16 words). */
#define KPV_KEY_BASE ((volatile uint32_t *)KEY_MANAGER_KPV_KEY_ENTRY_WORD_BASE_ADDR(0, 0))

/** @brief Pointer to the first word of slot [slot]. */
#define KPV_SLOT_BASE(slot) (KPV_KEY_BASE + (uint32_t)(slot)*ROM_KM_KPV_WORDS_PER_SLOT)

/** @brief Total 32-bit key words in the KPV (all slots combined). */
#define ROM_KM_KPV_TOTAL_WORDS ((uint16_t)(ROM_KM_KPV_NUM_SLOTS * ROM_KM_KPV_WORDS_PER_SLOT))

/*===========================================================================
 * Scrambler
 *===========================================================================*/

/**
 * @brief Load DRBG-random data into the KPV scrambler key register.
 *
 * Writes ROM_KM_SHRED_ITER+1 words from the hardware DRBG into the KPV
 * scrambler key.  No-ops if the scrambler is already locked.
 */
void rom_kpv_init_scrambler(void) {
    if (KPV_SCRAMBLER_CTRL.f.lock) return;

    for (uint8_t i = 0; i < ROM_KM_SHRED_ITER + 1; i++) KPV_SCRAMBLER_KEY.w = rom_drbg_get_word();
}

/**
 * @brief Set the scrambler enable bit in KPV_SCRAMBLER_CTRL.
 *
 * Enables XOR scrambling of KPV key data in SRAM.  Must be called
 * after rom_kpv_init_scrambler(); can be disabled (if not locked) for tests.
 */
void rom_kpv_scrambler_enable(void) {
    km_kpv__kpv_scrambler_ctrl_reg_t ctrl;
    ctrl.w = KPV_SCRAMBLER_CTRL.w;
    ctrl.f.enable = 1;
    KPV_SCRAMBLER_CTRL.w = ctrl.w;
}

/**
 * @brief Clear the scrambler enable bit (no-op if locked).
 *
 * Disables XOR scrambling so that raw stored data can be read back;
 * used by tests to verify shred and scramble behaviour.
 */
void rom_kpv_scrambler_disable(void) {
    if (KPV_SCRAMBLER_CTRL.f.lock) return;
    km_kpv__kpv_scrambler_ctrl_reg_t ctrl;
    ctrl.w = KPV_SCRAMBLER_CTRL.w;
    ctrl.f.enable = 0;
    KPV_SCRAMBLER_CTRL.w = ctrl.w;
}

/**
 * @brief Lock the scrambler configuration to prevent further changes.
 *
 * Once locked, enable/disable and key register writes are ignored until
 * the next hardware reset.
 */
void rom_kpv_scrambler_lock(void) {
    km_kpv__kpv_scrambler_ctrl_reg_t ctrl;
    ctrl.w = KPV_SCRAMBLER_CTRL.w;
    ctrl.f.lock = 1;
    KPV_SCRAMBLER_CTRL.w = ctrl.w;
}

/*===========================================================================
 * Shred and hardware erase
 *
 * One call chain, outermost first: shred_all -> shred_slot -> erase_slot.
 *===========================================================================*/

/**
 * @brief Shred all KPV slots via the hardware erase path.
 *
 * Calls rom_kpv_shred_slot on every slot, which erases each slot
 * ROM_KM_SHRED_ITER+1 times (overwriting the slot data with LFSR output
 * through the KPV scrambler and clearing the slot CTRL register), so this
 * also wipes write-locked slots.
 */
void rom_kpv_shred_all(void) {
    for (uint8_t s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++) rom_kpv_shred_slot(s);
}

/**
 * @brief Shred a single KPV slot via the hardware erase path.
 *
 * Calls rom_kpv_erase_slot on the slot ROM_KM_SHRED_ITER+1 times.  Each erase
 * overwrites the slot data with LFSR output (through the KPV scrambler) and
 * clears the slot CTRL register, so this also wipes write-locked slots.  A
 * sealed slot ends up retired instead of free.
 *
 * @param[in]  slot Slot index to shred.
 */
void rom_kpv_shred_slot(uint8_t slot) {
    for (uint8_t iter = 0; iter < ROM_KM_SHRED_ITER + 1; iter++) rom_kpv_erase_slot(slot);
}

/**
 * @brief Hardware-erase one slot, then wait for completion.
 *
 * Asserts CTRL.erase and busy-waits until hardware self-clears the erase bit.
 * Nothing gates an erase: not lock_write, not lock_use, not a seal.  An
 * unsealed slot comes back with its CTRL cleared and is reusable; a sealed slot
 * is retired instead (lock_write held, lock_use set), its data destroyed.
 *
 * @param[in] slot Slot index.
 */
void rom_kpv_erase_slot(uint8_t slot) {
    /* The write-1 trigger is issued three times so a single skipped store
     * (e.g. from a fault-injection glitch) cannot prevent the erase from
     * starting. */
    km_kpv__ctrl_reg_t ctrl;
    ctrl.w = KPV_CTRL(slot).w;
    ctrl.f.erase = 1;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;

    /* Wait until hardware self-clears the erase bit: the slot data has been
     * overwritten and the slot's lock state settled. */
    while (KPV_CTRL(slot).f.erase)
        ;
}

/*===========================================================================
 * Write slot
 *===========================================================================*/

/**
 * @brief Write key words into one KPV slot.
 *
 * @param[in] slot     Slot index.
 * @param[in] words    Key data array.
 * @param[in] n_words  Words to write (1-16).
 * @return 0 on success, -1 if n_words is out of range or the slot is
 *         write-locked.
 */
int rom_kpv_write_slot(uint8_t slot, const uint32_t *words, uint8_t n_words) {
    /* A slot is ROM_KM_KPV_WORDS_PER_SLOT words and the slots are contiguous,
     * so an over-long count would run into the next slot. */
    if (n_words == 0 || n_words > ROM_KM_KPV_WORDS_PER_SLOT) return -1;

    if (KPV_CTRL(slot).f.lock_write) return -1;

    for (uint8_t w = 0; w < n_words; w++) KPV_KEY_WORD(slot, w) = words[w];

    return 0;
}

/*===========================================================================
 * Read slot
 *===========================================================================*/

/**
 * @brief Read key words out of one KPV slot.
 *
 * @param[in]  slot     Slot index.
 * @param[out] words    Output buffer (>= n_words words).
 * @param[in]  n_words  Words to read (1-16).
 * @return 0 on success, -1 if n_words is out of range or the slot is
 *         read-locked.
 */
int rom_kpv_read_slot(uint8_t slot, uint32_t *words, uint8_t n_words) {
    /* Bounded for the same reason as rom_kpv_write_slot: an over-long count
     * would read out of the slot and into the next one. */
    if (n_words == 0 || n_words > ROM_KM_KPV_WORDS_PER_SLOT) return -1;

    if (KPV_CTRL(slot).f.lock_use) return -1;

    for (uint8_t w = 0; w < n_words; w++) words[w] = KPV_KEY_WORD(slot, w);

    return 0;
}

/*===========================================================================
 * Lock functions
 *===========================================================================*/

/**
 * @brief Set the write-lock bit on one slot, with triple write.
 *
 * @param[in] slot Slot index.
 */
void rom_kpv_write_lock(uint8_t slot) {
    /* Triple-write convention: 3 writes ensure the lock commits even if a
     * fault-injection glitch skips a store.  lock_write is woset, so the
     * repeated writes are idempotent and the zero-valued bits leave the
     * slot's other CTRL fields (incl. erase) untouched. */
    km_kpv__ctrl_reg_t ctrl = {0};
    ctrl.f.lock_write = 1;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;
}

/**
 * @brief Set read-lock (lock_use) on one slot, preventing further key reads.
 *
 * @param[in] slot Slot index.
 */
void rom_kpv_read_lock(uint8_t slot) {
    /* Triple-write convention — same rationale as rom_kpv_write_lock. */
    km_kpv__ctrl_reg_t ctrl = {0};
    ctrl.f.lock_use = 1;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;
}

int rom_kpv_seal_slot(uint8_t slot) {
    /* Only the seal is written; hardware sets lock_write alongside it. */
    km_kpv__ctrl_reg_t ctrl = {0};
    ctrl.f.seal = 1;
    /* Triple-write convention — same rationale as rom_kpv_write_lock. */
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;
    KPV_CTRL(slot).w = ctrl.w;

    return rom_kpv_slot_sealed(slot) ? 0 : -1;
}

int rom_kpv_slot_sealed(uint8_t slot) {
    km_kpv__ctrl_reg_t ctrl;
    ctrl.w = KPV_CTRL(slot).w;

    return (ctrl.f.lock_write && ctrl.f.seal) ? 1 : 0;
}

int rom_kpv_slot_retired(uint8_t slot) {
    km_kpv__ctrl_reg_t ctrl;
    ctrl.w = KPV_CTRL(slot).w;

    return (ctrl.f.seal && ctrl.f.lock_use) ? 1 : 0;
}
