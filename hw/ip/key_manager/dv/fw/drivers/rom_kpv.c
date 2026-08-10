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
 * write-locked slots are wiped too.
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

/** @brief Base of KPV key array (32 slots × 16 words = 512 words). */
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
 * clears the slot CTRL register, so this also wipes write-locked slots.
 *
 * @param[in]  slot Slot index to shred (EXTEND determines the span erased).
 */
void rom_kpv_shred_slot(uint8_t slot) {
    for (uint8_t iter = 0; iter < ROM_KM_SHRED_ITER + 1; iter++) rom_kpv_erase_slot(slot);
}

/**
 * @brief Hardware-erase the base slot and all extended slots, then wait.
 *
 * Asserts CTRL.erase on every slot spanned by the key and busy-waits until
 * hardware self-clears each erase bit (slot data overwritten with LFSR output
 * and CTRL cleared, incl. locks — erase is not gated by the slot locks).
 *
 * @param[in] base_slot First slot index (EXTEND field determines span).
 */
void rom_kpv_erase_slot(uint8_t base_slot) {
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;

    /* Assert the erase trigger on every slot of the key.  The write-1 trigger
     * is issued three times per slot so a single skipped store (e.g. from a
     * fault-injection glitch) cannot prevent the erase from starting. */
    for (uint8_t s = 0; s <= extend; s++) {
        km_kpv__ctrl_reg_t ctrl;
        ctrl.w = KPV_CTRL(base_slot + s).w;
        ctrl.f.erase = 1;
        KPV_CTRL(base_slot + s).w = ctrl.w;
        KPV_CTRL(base_slot + s).w = ctrl.w;
        KPV_CTRL(base_slot + s).w = ctrl.w;
    }

    /* Wait until hardware self-clears each erase bit: the slot data has been
     * overwritten and its CTRL register (incl. locks) cleared, so the slot is
     * reusable. */
    for (uint8_t s = 0; s <= extend; s++) {
        while (KPV_CTRL(base_slot + s).f.erase)
            ;
    }
}

/*===========================================================================
 * Write key
 *===========================================================================*/

/**
 * @brief Write a key into one or more consecutive KPV slots.
 *
 * Configures EXTEND and LAST_DWORD control fields. The permitted-destination
 * mask is tracked in the software key registry (rom_keyreg), not in KPV CTRL.
 *
 * @param[in] base_slot  First slot index.
 * @param[in] key        Key data array.
 * @param[in] key_len    Key length in 32-bit words.
 * @return 0 on success, -1 if any required slot is write-locked.
 */
int rom_kpv_write_key(uint8_t base_slot, const uint32_t *key, uint8_t key_len) {
    uint8_t extend = (uint8_t)((key_len - 1) / ROM_KM_KPV_WORDS_PER_SLOT);
    uint8_t num_slots = extend + 1;

    /* Verify none of the required slots are write-locked. */
    for (uint8_t s = 0; s < num_slots; s++) {
        if (KPV_CTRL(base_slot + s).f.lock_write) return -1;
    }

    /* Configure control registers for each slot. */
    uint8_t words_written = 0;
    for (uint8_t s = 0; s < num_slots; s++) {
        km_kpv__ctrl_reg_t ctrl;
        ctrl.w = 0;
        ctrl.f.extend = ((s == 0) ? extend : 0) & 0x7u;

        if (s == num_slots - 1) {
            uint8_t rem = key_len % ROM_KM_KPV_WORDS_PER_SLOT;
            ctrl.f.last_dword = ((rem == 0) ? 15 : (rem - 1)) & 0xFu;
        } else {
            ctrl.f.last_dword = 15u & 0xFu;
        }

        KPV_CTRL(base_slot + s).w = ctrl.w;

        /* Write key data words for this slot. */
        uint8_t words_in_slot =
            (s == num_slots - 1) ? (uint8_t)(key_len - words_written) : ROM_KM_KPV_WORDS_PER_SLOT;

        for (uint8_t w = 0; w < words_in_slot; w++)
            KPV_KEY_WORD(base_slot + s, w) = key[words_written + w];

        words_written += words_in_slot;
    }

    return 0;
}

/*===========================================================================
 * Get key info (length from control registers only)
 *===========================================================================*/

/**
 * @brief Get key length from KPV control registers.
 *
 * Performs same validation as rom_kpv_read_key; does not read key data.
 *
 * @param[in]  base_slot  Base slot index (0-31).
 * @param[out] key_len    Receives total key length in words.
 * @return 0 on success, -1 if read-locked or malformed.
 */
int rom_kpv_get_key_info(uint8_t base_slot, uint8_t *key_len) {
    km_kpv__ctrl_reg_t base_ctrl;
    base_ctrl.w = KPV_CTRL(base_slot).w;

    uint8_t extend = (uint8_t)base_ctrl.f.extend;
    uint8_t num_slots = extend + 1;

    for (uint8_t s = 0; s < num_slots; s++) {
        if (KPV_CTRL(base_slot + s).f.lock_use) return -1;
    }

    for (uint8_t s = 0; s < num_slots - 1; s++) {
        if (KPV_CTRL(base_slot + s).f.last_dword != 15) return -1;
    }

    km_kpv__ctrl_reg_t final_ctrl;
    final_ctrl.w = KPV_CTRL(base_slot + extend).w;
    *key_len = (uint8_t)(ROM_KM_KPV_WORDS_PER_SLOT * extend + final_ctrl.f.last_dword + 1);
    return 0;
}

/*===========================================================================
 * Read key
 *===========================================================================*/

/**
 * @brief Read a multi-slot key from the KPV.
 *
 * Reconstructs total length from EXTEND and LAST_DWORD control fields.
 *
 * @param[in]  base_slot  First slot index (must have EXTEND set).
 * @param[out] key        Output buffer (caller must provide >= key_len words).
 * @param[out] key_len    Receives the reconstructed key length in words.
 * @return 0 on success, -1 if any slot is read-locked or malformed.
 */
int rom_kpv_read_key(uint8_t base_slot, uint32_t *key, uint8_t *key_len) {
    if (rom_kpv_get_key_info(base_slot, key_len) < 0) return -1;

    uint8_t total_len = *key_len;
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;
    uint8_t num_slots = extend + 1;

    /* Read key data from all slots. */
    uint8_t words_read = 0;
    for (uint8_t s = 0; s < num_slots; s++) {
        uint8_t words_in_slot =
            (s == num_slots - 1) ? (uint8_t)(total_len - words_read) : ROM_KM_KPV_WORDS_PER_SLOT;

        for (uint8_t w = 0; w < words_in_slot; w++)
            key[words_read + w] = KPV_KEY_WORD(base_slot + s, w);

        words_read += words_in_slot;
    }

    return 0;
}

/*===========================================================================
 * Lock functions
 *===========================================================================*/

/**
 * @brief Set the write-lock bit on all slots spanned by a multi-slot key.
 *
 * @param[in] base_slot First slot index (EXTEND field determines span).
 */
void rom_kpv_write_lock(uint8_t base_slot) {
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;

    for (uint8_t s = 0; s <= extend; s++) {
        km_kpv__ctrl_reg_t ctrl;
        ctrl.w = KPV_CTRL(base_slot + s).w;
        ctrl.f.lock_write = 1;
        KPV_CTRL(base_slot + s).w = ctrl.w;
    }
}

/**
 * @brief Set read-lock (lock_use) on all slots spanned by a multi-slot key.
 *
 * Prevents further key reads.
 *
 * @param[in] base_slot First slot index (EXTEND field determines span).
 */
void rom_kpv_read_lock(uint8_t base_slot) {
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;

    for (uint8_t s = 0; s <= extend; s++) {
        km_kpv__ctrl_reg_t ctrl;
        ctrl.w = KPV_CTRL(base_slot + s).w;
        ctrl.f.lock_use = 1;
        KPV_CTRL(base_slot + s).w = ctrl.w;
    }
}
