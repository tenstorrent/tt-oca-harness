/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_otp.h
 * @brief OTP readout driver for Key Manager ROM firmware.
 *
 * Provides readers for every OTP field exposed in the KMCSR:
 *   - `rom_otp_read_life_cycle()`      — 8-bit differential-encoded LC state.
 *   - `rom_otp_read_demotion()`        — 4-bit differential-encoded demotion.
 *   - `rom_otp_read_chiplet_uid()`     — 256-bit CHIPLET_UID, dual-rail verified.
 *   - `rom_otp_read_sip_uid()`         — 256-bit SIP_UID, dual-rail verified.
 *   - `rom_otp_read_sys_uid()`         — 256-bit SYS_UID, dual-rail verified.
 *   - `rom_otp_read_class_key()`       — 256-bit CLASS_KEY, dual-rail verified.
 *   - `rom_otp_set_read_lock()`        — Applies OTP_READ_LOCK bits (warm-reset domain,
 * triple-write).
 *   - `rom_otp_set_read_lock_cold()`   — Applies OTP_READ_LOCK_COLD bits (cold-reset domain,
 * triple-write).
 *   - `rom_otp_get_change_status()`    — Read OTP_CHANGE_STATUS (which fields changed).
 *   - `rom_otp_clear_change_status()`  — W1C-clear OTP_CHANGE_STATUS bits.
 *
 * Dual-rail readers verify that each value word equals ~complement word.
 * Returns 0 on success, -1 on dual-rail integrity failure.
 *
 * All reads from KMCSR registers are volatile (hardware read-through).
 * Locked fields return zero from hardware regardless of actual OTP content.
 */

#ifndef ROM_OTP_H
#define ROM_OTP_H

#include <stdint.h>

#include "key_manager_fw.h"
#include "rom_defs.h"

/** @brief Number of 32-bit words in a 256-bit dual-rail OTP field. */
#define ROM_KM_OTP_WORDS 8

/** @brief IRQ_STATUS bit raised when a decoded OTP field value changes. */
#ifndef ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK
#define ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK KM_CSR__IRQ_STATUS_REG__OTP_CHANGE_bm
#endif

/*---------------------------------------------------------------------------
 * Register accessors (volatile pointer casts to generated struct types)
 *---------------------------------------------------------------------------*/

/** @brief OTP_LIFE_CYCLE register. */
#define ROM_OTP_LIFE_CYCLE_REG \
    (*(volatile km_csr__otp_life_cycle_reg_t *)KEY_MANAGER_KMCSR_OTP_LIFE_CYCLE_BASE_ADDR)
/** @brief OTP_DEMOTION_STATE register. */
#define ROM_OTP_DEMOTION_STATE_REG \
    (*(volatile km_csr__otp_demotion_state_reg_t *)KEY_MANAGER_KMCSR_OTP_DEMOTION_STATE_BASE_ADDR)
/** @brief OTP_READ_LOCK register (write-1-only, warm reset domain). */
#define ROM_OTP_READ_LOCK_REG \
    (*(volatile km_csr__otp_read_lock_reg_t *)KEY_MANAGER_KMCSR_OTP_READ_LOCK_BASE_ADDR)
/** @brief OTP_READ_LOCK_COLD register (write-1-only, cold reset domain). */
#define ROM_OTP_READ_LOCK_COLD_REG \
    (*(volatile km_csr__otp_read_lock_cold_reg_t *)KEY_MANAGER_KMCSR_OTP_READ_LOCK_COLD_BASE_ADDR)
/** @brief OTP_CHANGE_STATUS register (sticky, W1C). */
#define ROM_OTP_CHANGE_STATUS_REG \
    (*(volatile km_csr__otp_change_status_reg_t *)KEY_MANAGER_KMCSR_OTP_CHANGE_STATUS_BASE_ADDR)

/**
 * @brief Read and decode OTP_LIFE_CYCLE (4-bit dual-rail value).
 *
 * Reads the 8-bit differential field {~lc[3:0], lc[3:0]}, verifies the
 * complement relationship, and writes the decoded 4-bit life-cycle value.
 *
 * @param[out] lc_out  Decoded 4-bit life-cycle state. Set to 0 on failure.
 *                     May be NULL to check integrity only.
 * @return 0 on success, -1 if the dual-rail integrity check failed (also
 *         returned when the field is read-locked, which reads back as 0).
 */
int rom_otp_read_life_cycle(uint8_t *lc_out);

/**
 * @brief Read and decode OTP_DEMOTION_STATE (two 1-bit dual-rail values).
 *
 * Verifies the complement relationship of each 2-bit differential field and
 * writes the decoded value as {demote_2, demote_1} (bit1 = demote_2,
 * bit0 = demote_1).
 *
 * @param[out] demote_out  Decoded 2-bit demotion state. Set to 0 on failure.
 *                         May be NULL to check integrity only.
 * @return 0 on success, -1 if the dual-rail integrity check failed (also
 *         returned when the field is read-locked, which reads back as 0).
 */
int rom_otp_read_demotion(uint8_t *demote_out);

/**
 * @brief Read CHIPLET_UID from KMCSR dual-rail registers with integrity check.
 *
 * Reads the 8 value words and 8 complement words, verifies value[i] == ~cpl[i]
 * for each word, and copies the decoded value to @p out.
 *
 * @param[out] out  Array of ROM_KM_OTP_WORDS (8) uint32_t words.
 *                  Set to all-zero if integrity check fails.
 * @return 0 on success, -1 if dual-rail integrity check failed.
 */
int rom_otp_read_chiplet_uid(uint32_t out[ROM_KM_OTP_WORDS]);

/**
 * @brief Read SIP_UID from KMCSR dual-rail registers with integrity check.
 *
 * @param[out] out  Array of ROM_KM_OTP_WORDS (8) uint32_t words.
 * @return 0 on success, -1 if dual-rail integrity check failed.
 */
int rom_otp_read_sip_uid(uint32_t out[ROM_KM_OTP_WORDS]);

/**
 * @brief Read SYS_UID from KMCSR dual-rail registers with integrity check.
 *
 * @param[out] out  Array of ROM_KM_OTP_WORDS (8) uint32_t words.
 * @return 0 on success, -1 if dual-rail integrity check failed.
 */
int rom_otp_read_sys_uid(uint32_t out[ROM_KM_OTP_WORDS]);

/**
 * @brief Read CLASS_KEY from KMCSR dual-rail registers with integrity check.
 *
 * @param[out] out  Array of ROM_KM_OTP_WORDS (8) uint32_t words.
 * @return 0 on success, -1 if dual-rail integrity check failed.
 */
int rom_otp_read_class_key(uint32_t out[ROM_KM_OTP_WORDS]);

/**
 * @brief Set OTP read-lock bits (write-1-only, warm reset domain).
 *
 * Writes @p lock_bits to OTP_READ_LOCK three consecutive times to match the
 * triple-write convention (ROM_KM_SHRED_ITER + 1 = 3).  The woset attribute
 * makes repeated writes idempotent: already-set bits are unaffected.
 *
 * After locking, hardware returns zero for locked fields regardless of OTP.
 * Cleared by warm reset (and cold reset, which always asserts warm reset).
 *
 * @param lock_bits  Bitmask of fields to lock (use KM_CSR__OTP_READ_LOCK_REG__*_bm
 *                   from km_csr.h, or the ROM_KM_OTP_LOCK_*_MASK aggregates).
 *                   Writing 0 has no effect; bits can only be set, not cleared.
 */
void rom_otp_set_read_lock(uint32_t lock_bits);

/**
 * @brief Set OTP cold-reset-domain read-lock bits (write-1-only, cold reset domain).
 *
 * Writes @p lock_bits to OTP_READ_LOCK_COLD three consecutive times (triple-write
 * convention).  The woset attribute makes repeated writes idempotent.
 *
 * The effective read-lock for each OTP field is the OR of OTP_READ_LOCK and
 * OTP_READ_LOCK_COLD.  Bits set here survive warm reset and are cleared only by
 * cold reset.  This allows the SEP host (via CMD_OTP_READ_LOCK_COLD) to apply
 * read-locks that persist across warm resets.
 *
 * After locking, hardware returns zero for the locked field(s) regardless of OTP.
 *
 * @param lock_bits  Bitmask of fields to lock (use KM_CSR__OTP_READ_LOCK_COLD_REG__*_bm
 *                   from km_csr.h).  Writing 0 has no effect; bits can
 *                   only be set, not cleared.
 */
void rom_otp_set_read_lock_cold(uint32_t lock_bits);

/**
 * @brief Read OTP_CHANGE_STATUS register.
 *
 * Each set bit indicates the corresponding OTP field's decoded value changed
 * since the prior cycle.  Call after an OTP_CHANGE IRQ.
 *
 * @return Bitmask of changed fields (KM_CSR__OTP_CHANGE_STATUS_REG__*_bm bit positions).
 */
uint32_t rom_otp_get_change_status(void);

/**
 * @brief Clear OTP_CHANGE_STATUS bits (write-1-to-clear).
 *
 * @param mask  Bitmask of bits to clear (write 1 to clear each set bit).
 */
void rom_otp_clear_change_status(uint32_t mask);

/**
 * @brief OTP change notification hook (weak, overridable by tests/application).
 *
 * Called from rom_isr_kmcsr() when the OTP_CHANGE IRQ fires.  @p changed_mask
 * holds the snapshot of OTP_CHANGE_STATUS read before the W1C clear.
 *
 * The default implementation does nothing.  Override in test code or
 * application firmware to react to live OTP value changes.
 *
 * @param changed_mask  Bitmask of changed fields (KM_CSR__OTP_CHANGE_STATUS_REG__*_bm bit
 * positions).
 */
void rom_otp_on_change(uint32_t changed_mask);

#endif /* ROM_OTP_H */
