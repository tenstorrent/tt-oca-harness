/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_handover.h
 * @brief KM ROM-to-SRAM handover sequence declarations.
 *
 * Implements the three handover paths:
 *   CMD_SRAM_LOAD_EXEC (0x11) — stream firmware image from mailbox FIFO,
 *     verify CRC-32C, lock sensitive data and firmware SRAM regions, then
 *     execute the stack-less assembly handoff.
 *   CMD_SRAM_EXEC (0x12) — execute the same handoff against previously
 *     loaded firmware (sram_fw_size must be non-zero).
 *
 * Both paths send their own RESP_CMD success response directly to the
 * mailbox (bypassing rom_tx_msgbuf) before the point of no return, so the
 * dispatcher's send_resp_cmd() is never reached.
 *
 * Assembly handoff: rom_handover_jump.S — scrambles the entire SRAM (locked
 * regions are silently skipped by hardware), clears all GPRs, then jumps to
 * 0x4000.  Note that locking and IRQ disable all occur in C
 * (rom_handover_finish) before entering the stack-less assembly path; this is
 * required because the assembly wipes the C stack.
 */

#ifndef ROM_HANDOVER_H
#define ROM_HANDOVER_H

#include <stdint.h>

/**
 * @brief Stream fw_words from inbound FIFO to SRAM, verify CRC-32C, then
 *        execute the handover sequence (never returns).
 *
 * Called by rom_cmd_sram_load_exec after initial bounds validation.  This
 * function owns the rest of the load-and-exec protocol:
 *   1. Clear sram_fw_size to 0 (invalidate any previous load).
 *   2. Wait for TX buffer to drain, disable mailbox IRQs, send a direct
 *      RESP_CMD success (the "confirmation" that tells SEP to stream the image).
 *   3. Re-enable the outbound drain IRQ; keep inbound IRQ disabled.
 *   4. Stream fw_words words from the inbound FIFO into SRAM starting at
 *      ROM_KM_SRAM_BASE, computing CRC-32C incrementally per word.
 *      Per-word: abort with ROM_KM_UFAULT_FW_STACK_OVF if the destination
 *      address reaches or exceeds load_limit (region-aligned stack guard).
 *   5. Read the trailing CRC-32C word (with separator).  On mismatch, trigger
 *      ROM_KM_UFAULT_FW_CRC (never returns).
 *   6. On match: set sram_fw_size = fw_words * 4, call rom_handover_finish.
 *
 * @param cmd_seq   Sequence number echo for the direct RESP_CMD confirmation.
 * @param fw_words  Firmware image size in 32-bit words (already validated > 0).
 * @param load_limit Region-aligned exclusive upper bound for the firmware load
 *                   area (the static __km_fw_load_limit passed by the caller).
 */
__attribute__((noreturn)) void rom_handover_load_and_exec(uint8_t cmd_seq, uint32_t fw_words,
                                                          uint32_t load_limit);

/**
 * @brief Send direct RESP_CMD success and jump to pre-loaded SRAM firmware
 *        (never returns).
 *
 * Called by rom_cmd_sram_exec after confirming sram_fw_size > 0.
 *
 * @param cmd_seq      Sequence number echo for the direct RESP_CMD.
 * @param fw_size_bytes Byte size of the loaded firmware (from sram_fw_size).
 */
__attribute__((noreturn)) void rom_handover_exec_existing(uint8_t cmd_seq, uint32_t fw_size_bytes);

/**
 * @brief Lock sensitive data before handover (used by both SRAM-exec paths).
 *
 * - OTP read-lock: sets ROM_KM_OTP_LOCK_SECRET_MASK (triple-write).
 * - SRAM region 31 write-lock: rom_persist_lock().
 * - KPV: rom_handover_lock_kpv_root_keys() (read-lock live slots, shred free).
 */
void rom_handover_lock_sensitive(void);

/**
 * @brief Shred all crypto-engine sideload key registers before handover.
 *
 * The HMAC/KMAC/AES/OTBN and Adams Bridge seed key-share register banks live
 * outside the SRAM address space, so the whole-SRAM scramble in
 * rom_handover_jump.S cannot reach them. This overwrites each engine's key
 * shares with PRNG data and clears key_valid, and zeroizes the ML-KEM shared
 * key, denying mutable firmware any key material the ROM previously sideloaded.
 */
void rom_handover_shred_sideload_keys(void);

/**
 * @brief C portion of the handover finish sequence (called by both exec paths).
 *
 * Steps (in order):
 *   1. rom_handover_shred_sideload_keys() — overwrite HMAC/KMAC/AES/OTBN and
 *      ABR seed key registers and zeroize the ML-KEM shared key (run first,
 *      while DRBG and fault detection are still live).
 *   2. rom_handover_lock_sensitive() — OTP + persist + KPV (read-lock live
 *      slots, shred free slots).
 *   3. Compute and apply the SRAM write-lock mask for the firmware regions.
 *   4. Reseed the PRNG from the DRBG (fresh entropy for the scramble seed),
 *      before IRQs are disabled so a DRBG fault is still reported.
 *   5. Disable ALL KMCSR IRQs (write 0 to KMCSR IRQ_ENABLE) and clear sticky
 *      IRQ status bits (W1C) to prevent spurious faults in mutable firmware.
 *   6. Spin until the outbound FIFO is empty (SEP has drained the RESP_CMD),
 *      then flush both mailbox FIFOs to erase residual inbound payload.
 *   7. Disable ALL mailbox IRQ enables.
 *   8. Mask all CPU IRQs via rom_picorv32_maskirq(0xFFFFFFFF).
 *   9. Capture PRNG seed from rom_prng_state (four 32-bit words).
 *  10. Tail-call rom_handover_jump(s0,s1,s2,s3) — never returns.
 *
 * @param fw_size_bytes Byte size of the firmware image (used to compute lock mask).
 */
__attribute__((noreturn)) void rom_handover_finish(uint32_t fw_size_bytes);

/**
 * @brief Deny mutable firmware access to KPV key material before handover.
 *
 * KPV key data has no warm reset and is descrambled on KM-port reads, and the
 * load path only write-locks (not read-locks) provisioned keys, so live keys
 * would otherwise be plaintext-readable by mutable firmware.  Using the
 * firmware key registry to classify each slot, this read-locks (lock_use)
 * every registered slot and overwrites every free slot with pseudorandom data
 * (falling back to a read-lock if a free slot is write-locked and cannot be
 * shredded).
 */
void rom_handover_lock_kpv_root_keys(void);

/**
 * @brief Stack-less SRAM scramble and jump (implemented in rom_handover_jump.S).
 *
 * Runs entirely from registers.  No stack use from this point forward.
 *
 * Actions:
 *   1. Overwrite the entire SRAM (0x4000-0x8000) with a register-seeded
 *      xoshiro128++ pattern.  Hardware silently drops writes to write-locked
 *      regions (firmware image, rom_persist), so only unlocked data is erased.
 *   2. Clear all GPRs (x1-x15).
 *   3. fence; jump to 0x4000.
 *
 * @param s0-s3  xoshiro128++ initial state words (passed in a0-a3).
 */
__attribute__((noreturn)) void rom_handover_jump(uint32_t s0, uint32_t s1, uint32_t s2,
                                                 uint32_t s3);

#endif /* ROM_HANDOVER_H */
