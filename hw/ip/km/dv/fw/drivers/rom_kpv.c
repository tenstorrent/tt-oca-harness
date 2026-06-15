/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kpv.c
 * @brief Key Provisioning Vault (KPV) driver implementation
 *
 * Scrambler control, slot shredding (single and bulk), key read/write, and
 * lock operations.  Shred routines use rom_shred_region for pseudorandom
 * overwrite (full KPV as one region when no slots are write-locked,
 * otherwise per-slot).
 */

#include "rom_kpv.h"
#include "rom_defs.h"
#include "rom_prng.h"
#include "rom_shred.h"
#include "rom_drbg.h"
#include "key_manager_regs.h"

/** @brief KPV scrambler key register (volatile, write-only). */
#define KPV_SCRAMBLER_KEY  (*(volatile KM_KPV_KPV_SCRAMBLER_KEY_REG_reg_u *)KPV_KPV_SCRAMBLER_KEY_REG_ADDR)
/** @brief KPV scrambler control register (volatile, R/W). */
#define KPV_SCRAMBLER_CTRL (*(volatile KM_KPV_KPV_SCRAMBLER_CTRL_REG_reg_u *)KPV_KPV_SCRAMBLER_CTRL_REG_ADDR)

/** @brief Base of KPV key array (32 slots × 16 words = 512 words). */
#define KPV_KEY_BASE  ((volatile uint32_t *)KPV_KEY_ENTRY_0__WORD_0__REG_ADDR)

/** @brief Pointer to the first word of slot [slot]. */
#define KPV_SLOT_BASE(slot)  (KPV_KEY_BASE + (uint32_t)(slot) * ROM_KM_KPV_WORDS_PER_SLOT)

/** @brief Total 32-bit key words in the KPV (all slots combined). */
#define ROM_KM_KPV_TOTAL_WORDS  ((uint16_t)(ROM_KM_KPV_NUM_SLOTS * ROM_KM_KPV_WORDS_PER_SLOT))

/*===========================================================================
 * Scrambler
 *===========================================================================*/

/**
 * @brief Load DRBG-random data into the KPV scrambler key register.
 *
 * Writes ROM_KM_SHRED_ITER+1 words from the hardware DRBG into the KPV
 * scrambler key.  No-ops if the scrambler is already locked.
 */
void rom_kpv_init_scrambler(void)
{
    if (KPV_SCRAMBLER_CTRL.f.lock)
        return;

    for (uint8_t i = 0; i < ROM_KM_SHRED_ITER + 1; i++)
        KPV_SCRAMBLER_KEY.val = rom_drbg_get_word();
}

/**
 * @brief Set the scrambler enable bit in KPV_SCRAMBLER_CTRL.
 *
 * Enables XOR scrambling of KPV key data in SRAM.  Must be called
 * after rom_kpv_init_scrambler(); can be disabled (if not locked) for tests.
 */
void rom_kpv_scrambler_enable(void)
{
    KM_KPV_KPV_SCRAMBLER_CTRL_REG_reg_u ctrl;
    ctrl.val = KPV_SCRAMBLER_CTRL.val;
    ctrl.f.enable = 1;
    KPV_SCRAMBLER_CTRL.val = ctrl.val;
}

/**
 * @brief Clear the scrambler enable bit (no-op if locked).
 *
 * Disables XOR scrambling so that raw stored data can be read back;
 * used by tests to verify shred and scramble behaviour.
 */
void rom_kpv_scrambler_disable(void)
{
    if (KPV_SCRAMBLER_CTRL.f.lock)
        return;
    KM_KPV_KPV_SCRAMBLER_CTRL_REG_reg_u ctrl;
    ctrl.val = KPV_SCRAMBLER_CTRL.val;
    ctrl.f.enable = 0;
    KPV_SCRAMBLER_CTRL.val = ctrl.val;
}

/**
 * @brief Lock the scrambler configuration to prevent further changes.
 *
 * Once locked, enable/disable and key register writes are ignored until
 * the next hardware reset.
 */
void rom_kpv_scrambler_lock(void)
{
    KM_KPV_KPV_SCRAMBLER_CTRL_REG_reg_u ctrl;
    ctrl.val = KPV_SCRAMBLER_CTRL.val;
    ctrl.f.lock = 1;
    KPV_SCRAMBLER_CTRL.val = ctrl.val;
}

/*===========================================================================
 * Shred all
 *===========================================================================*/

/**
 * @brief Shred all KPV slots with pseudorandom data.
 *
 * If any slot is write-locked, returns -1 without shredding.  Otherwise
 * clears slot control registers and shreds the entire key array (512 words)
 * in one call to rom_shred_region.
 *
 * @param[in] prng PRNG state (re-seeded from DRBG each pass).
 * @return 0 on success, -1 if any slot is write-locked.
 */
int rom_kpv_shred_all(rom_km_prng_state_t *prng)
{
    for (uint8_t s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++) {
        if (KPV_CTRL(s).f.lock_write)
            return -1;
    }

    for (uint8_t s = 0; s < ROM_KM_KPV_NUM_SLOTS; s++)
        KPV_CTRL(s).val = 0;

    rom_shred_region(KPV_KEY_BASE, ROM_KM_KPV_TOTAL_WORDS, prng, 1);
    return 0;
}

/*===========================================================================
 * Shred single slot
 *===========================================================================*/

/**
 * @brief Shred a single KPV slot with pseudorandom data.
 *
 * @param[in]  slot Slot index to shred.
 * @param[in]  prng PRNG state (re-seeded from DRBG each pass).
 * @return 0 on success, -1 if the slot is write-locked.
 */
int rom_kpv_shred_slot(uint8_t slot, rom_km_prng_state_t *prng)
{
    if (KPV_CTRL(slot).f.lock_write)
        return -1;

    KPV_CTRL(slot).val = 0;
    rom_shred_region(KPV_SLOT_BASE(slot),
                     (uint16_t)ROM_KM_KPV_WORDS_PER_SLOT,
                     prng, 1);
    return 0;
}

/*===========================================================================
 * Write key
 *===========================================================================*/

/**
 * @brief Write a key into one or more consecutive KPV slots.
 *
 * Configures EXTEND, LAST_DWORD, and DEST_VALID control fields.
 *
 * @param[in] base_slot  First slot index.
 * @param[in] key        Key data array.
 * @param[in] key_len    Key length in 32-bit words.
 * @param[in] dest_valid Permitted destination engine bitmask.
 * @return 0 on success, -1 if any required slot is write-locked.
 */
int rom_kpv_write_key(uint8_t base_slot, const uint32_t *key,
                      uint8_t key_len, rom_km_dest_bits_t dest_valid)
{
    uint8_t extend = (uint8_t)((key_len - 1) / ROM_KM_KPV_WORDS_PER_SLOT);
    uint8_t num_slots = extend + 1;

    /* Verify none of the required slots are write-locked. */
    for (uint8_t s = 0; s < num_slots; s++) {
        if (KPV_CTRL(base_slot + s).f.lock_write)
            return -1;
    }

    /* Configure control registers for each slot. */
    uint8_t words_written = 0;
    for (uint8_t s = 0; s < num_slots; s++) {
        KM_KPV_CTRL_REG_reg_u ctrl;
        ctrl.val = 0;
        ctrl.f.extend = ((s == 0) ? extend : 0) & 0x7u;
        ctrl.f.dest_valid = dest_valid.raw;

        if (s == num_slots - 1) {
            uint8_t rem = key_len % ROM_KM_KPV_WORDS_PER_SLOT;
            ctrl.f.last_dword = ((rem == 0) ? 15 : (rem - 1)) & 0xFu;
        } else {
            ctrl.f.last_dword = 15u & 0xFu;
        }

        KPV_CTRL(base_slot + s).val = ctrl.val;

        /* Write key data words for this slot. */
        uint8_t words_in_slot = (s == num_slots - 1)
            ? (uint8_t)(key_len - words_written)
            : ROM_KM_KPV_WORDS_PER_SLOT;

        for (uint8_t w = 0; w < words_in_slot; w++)
            KPV_KEY_WORD(base_slot + s, w) = key[words_written + w];

        words_written += words_in_slot;
    }

    return 0;
}

/*===========================================================================
 * Get key info (length and dest_valid from control registers only)
 *===========================================================================*/

/**
 * @brief Get key length and dest_valid from KPV control registers.
 *
 * Performs same validation as rom_kpv_read_key; does not read key data.
 *
 * @param[in]  base_slot  Base slot index (0-31).
 * @param[out] key_len    Receives total key length in words.
 * @param[out] dest_valid Receives DEST_VALID bitmask from base slot.
 * @return 0 on success, -1 if read-locked or malformed.
 */
int rom_kpv_get_key_info(uint8_t base_slot, uint8_t *key_len, rom_km_dest_bits_t *dest_valid)
{
    KM_KPV_CTRL_REG_reg_u base_ctrl;
    base_ctrl.val = KPV_CTRL(base_slot).val;

    uint8_t extend = (uint8_t)base_ctrl.f.extend;
    uint8_t num_slots = extend + 1;

    for (uint8_t s = 0; s < num_slots; s++) {
        if (KPV_CTRL(base_slot + s).f.lock_use)
            return -1;
    }

    for (uint8_t s = 0; s < num_slots - 1; s++) {
        if (KPV_CTRL(base_slot + s).f.last_dword != 15)
            return -1;
    }

    KM_KPV_CTRL_REG_reg_u final_ctrl;
    final_ctrl.val = KPV_CTRL(base_slot + extend).val;
    *key_len = (uint8_t)(ROM_KM_KPV_WORDS_PER_SLOT * extend
                        + final_ctrl.f.last_dword + 1);
    dest_valid->raw = (uint8_t)base_ctrl.f.dest_valid;
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
 * @param[out] dest_valid Receives the DEST_VALID bitmask from the base slot.
 * @return 0 on success, -1 if any slot is read-locked or malformed.
 */
int rom_kpv_read_key(uint8_t base_slot, uint32_t *key,
                     uint8_t *key_len, rom_km_dest_bits_t *dest_valid)
{
    if (rom_kpv_get_key_info(base_slot, key_len, dest_valid) < 0)
        return -1;

    uint8_t total_len = *key_len;
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;
    uint8_t num_slots = extend + 1;

    /* Read key data from all slots. */
    uint8_t words_read = 0;
    for (uint8_t s = 0; s < num_slots; s++) {
        uint8_t words_in_slot = (s == num_slots - 1)
            ? (uint8_t)(total_len - words_read)
            : ROM_KM_KPV_WORDS_PER_SLOT;

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
void rom_kpv_write_lock(uint8_t base_slot)
{
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;

    for (uint8_t s = 0; s <= extend; s++) {
        KM_KPV_CTRL_REG_reg_u ctrl;
        ctrl.val = KPV_CTRL(base_slot + s).val;
        ctrl.f.lock_write = 1;
        KPV_CTRL(base_slot + s).val = ctrl.val;
    }
}

/**
 * @brief Set read-lock (lock_use) on all slots spanned by a multi-slot key.
 *
 * Prevents further key reads.
 *
 * @param[in] base_slot First slot index (EXTEND field determines span).
 */
void rom_kpv_read_lock(uint8_t base_slot)
{
    uint8_t extend = (uint8_t)KPV_CTRL(base_slot).f.extend;

    for (uint8_t s = 0; s <= extend; s++) {
        KM_KPV_CTRL_REG_reg_u ctrl;
        ctrl.val = KPV_CTRL(base_slot + s).val;
        ctrl.f.lock_use = 1;
        KPV_CTRL(base_slot + s).val = ctrl.val;
    }
}
