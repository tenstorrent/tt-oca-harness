/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_cmd.h
 * @brief Command dispatch and handler declarations for Key Manager firmware.
 *
 * Declares the command dispatch entry point and individual command handlers.
 * No-payload handlers take void; payload handlers take a const pointer to
 * their per-command args struct. Payload length validation is performed by
 * rom_cmd_dispatch before invoking the handler.
 */

#ifndef ROM_CMD_H
#define ROM_CMD_H

#include "rom_defs.h"

/**
 * @brief Dispatch a command to the appropriate handler.
 *
 * Validates payload length for the given command, then invokes the handler
 * with a typed args pointer (or no argument for no-payload commands).
 * Unknown IDs return ROM_KM_RC_INVALID_CMD.
 *
 * @param cmd_id Command ID from the message header.
 * @param cmd_seq Command sequence number (echoed in direct RESP_CMD by handover handlers).
 * @param payload_len Number of 32-bit payload words.
 * @param payload Pointer to payload words, or `NULL` if `payload_len == 0`.
 * @return Command result (return code + optional argument).
 */
rom_km_cmd_result_t rom_cmd_dispatch(uint8_t cmd_id, uint8_t cmd_seq, uint8_t payload_len,
                                     const uint32_t *payload);

/*===========================================================================
 * Individual Command Handlers
 *===========================================================================*/

/** @brief Return KMCSR hardware version register (CMD_HW_VER). */
rom_km_cmd_result_t rom_cmd_hw_ver(void);

/** @brief Return compile-time ROM firmware version (CMD_ROM_VER). */
rom_km_cmd_result_t rom_cmd_rom_ver(void);

/** @brief Reserved SRAM version query -- always returns FAILURE (CMD_SRAM_VER). */
rom_km_cmd_result_t rom_cmd_sram_ver(void);

/** @brief Return KMCSR RECOVERABLE_ERR register value (CMD_STAT). */
rom_km_cmd_result_t rom_cmd_stat(void);

/** @brief Clear the KMCSR RECOVERABLE_ERR register (CMD_RECOV_ACK). */
rom_km_cmd_result_t rom_cmd_recov_ack(void);

/** @brief Generate a random key in the KPV and return a handle (CMD_KEY_GENERATE). */
rom_km_cmd_result_t rom_cmd_key_generate(const rom_km_cmd_key_generate_args_t *args);

/** @brief Revoke a key by locking its KPV slots (CMD_KEY_REVOKE). */
rom_km_cmd_result_t rom_cmd_key_revoke(const rom_km_cmd_key_revoke_args_t *args);

/** @brief Transfer a key from the KPV to crypto engine(s) (CMD_KEY_TRANSFER). */
rom_km_cmd_result_t rom_cmd_key_transfer(const rom_km_cmd_key_transfer_args_t *args);

/** @brief Shred sideload keys in specified crypto engines (CMD_ENGINE_SHRED). */
rom_km_cmd_result_t rom_cmd_engine_shred(const rom_km_cmd_engine_shred_args_t *args);

/**
 * @brief Load SEP-supplied key material directly into KPV via mailbox (CMD_KEY_LOAD).
 *
 * Validates the variable-length payload in strict word order,
 * then delegates to rom_load_key() for KPV allocation and registration.
 * Does NOT call rom_cmd_validate_payload_length; length is validated internally
 * against KEY_SIZE.
 *
 * @param payload_len Number of 32-bit payload words received.
 * @param payload     Pointer to payload words (word 0 = KEY_SIZE, word 1 = DEST_VALID,
 *                    words 2..payload_len-1 = KEY_DATA).
 * @return Command result with success + packed return arg, or invalid_arg / failure.
 */
rom_km_cmd_result_t rom_cmd_key_load(uint8_t payload_len, const uint32_t *payload);

/** @brief Capture ML-KEM shared key from Adams Bridge into the KPV (CMD_ABR_SK_TRANSFER). */
rom_km_cmd_result_t rom_cmd_abr_sk_transfer(const rom_km_cmd_abr_sk_transfer_args_t *args);

/** @brief Set cold-reset-domain OTP read-lock bits; bits survive warm reset
 * (CMD_OTP_READ_LOCK_COLD). */
rom_km_cmd_result_t rom_cmd_otp_read_lock_cold(const rom_km_cmd_otp_read_lock_cold_args_t *args);

/*===========================================================================
 * Handover Command Handlers (0x10-0x12)
 *===========================================================================*/

/**
 * @brief Set the ROM-execution flag; ignore subsequent handover commands (CMD_EXEC_ROM).
 *
 * Calling this command commits the KM to continued ROM execution for the
 * lifetime of the current warm-reset epoch.  Any subsequent CMD_EXEC_ROM,
 * CMD_SRAM_LOAD_EXEC, or CMD_SRAM_EXEC returns FAILURE.
 *
 * @return Success.
 */
rom_km_cmd_result_t rom_cmd_exec_rom(void);

/**
 * @brief Accept firmware image via mailbox, load to SRAM, and execute (CMD_SRAM_LOAD_EXEC).
 *
 * If the handover-disabled flag is set (CMD_EXEC_ROM was previously received),
 * returns FAILURE immediately.  Otherwise validates FW_WORDS, performs a
 * static load-bounds check against __km_fw_load_limit, sends a direct RESP_CMD
 * confirmation, streams the image from the mailbox FIFO, verifies the appended
 * CRC-32C, and hands control to the loaded firmware.  Never returns on success.
 *
 * @param cmd_seq Sequence number echo for the direct confirmation RESP_CMD.
 * @param args    Parsed payload (FW_WORDS and reserved-bit check).
 * @return Error result if validation fails; never returns on success.
 */
rom_km_cmd_result_t rom_cmd_sram_load_exec(uint8_t cmd_seq,
                                           const rom_km_cmd_sram_load_exec_args_t *args);

/**
 * @brief Jump to pre-loaded mutable firmware in SRAM (CMD_SRAM_EXEC).
 *
 * If the handover-disabled flag is set, returns FAILURE.  If sram_fw_size is
 * zero (no firmware previously loaded), returns INVALID_ARG.  Otherwise sends
 * a direct RESP_CMD success and executes the handover sequence.  Never returns
 * on success.
 *
 * @param cmd_seq Sequence number echo for the direct RESP_CMD.
 * @return Error result if validation fails; never returns on success.
 */
rom_km_cmd_result_t rom_cmd_sram_exec(uint8_t cmd_seq);

#endif /* ROM_CMD_H */
