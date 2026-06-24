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
 * @param payload_len Number of 32-bit payload words.
 * @param payload Pointer to payload words, or `NULL` if `payload_len == 0`.
 * @return Command result (return code + optional argument).
 */
rom_km_cmd_result_t rom_cmd_dispatch(uint8_t cmd_id, uint8_t payload_len,
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

/** @brief Allocate consecutive KPV slots for SEP KPVLP loading (CMD_KPVLP_SLOT_REQ). */
rom_km_cmd_result_t rom_cmd_kpvlp_slot_req(const rom_km_cmd_slot_req_args_t *args);

/** @brief Register a key loaded by SEP through the KPVLP (CMD_KPVLP_KEY_REGISTER). */
rom_km_cmd_result_t rom_cmd_kpvlp_key_register(const rom_km_cmd_kpvlp_key_register_args_t *args);

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
 * Validates the variable-length payload in strict word order per FR-2739-015,
 * then delegates to rom_load_key() for KPV allocation and registration.
 * Does NOT call rom_cmd_validate_payload_length; length is validated internally
 * against KEY_SIZE (FR-2739-001, FR-2739-015).
 *
 * @param payload_len Number of 32-bit payload words received.
 * @param payload     Pointer to payload words (word 0 = KEY_SIZE, word 1 = DEST_VALID,
 *                    words 2..payload_len-1 = KEY_DATA).
 * @return Command result with success + packed return arg, or invalid_arg / failure.
 */
rom_km_cmd_result_t rom_cmd_key_load(uint8_t payload_len, const uint32_t *payload);

#endif /* ROM_CMD_H */
