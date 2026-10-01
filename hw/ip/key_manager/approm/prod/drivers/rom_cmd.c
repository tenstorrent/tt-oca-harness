/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_cmd.c
 * @brief Command dispatch and handler implementations.
 *
 * Maps wire command IDs to typed handlers and returns normalized
 * `rom_km_cmd_result_t` results used by the message RX path.
 */

#include "rom_cmd.h"
#include "rom_defs.h"
#include "rom_state.h"
#include "rom_kpv.h"
#include "rom_keyreg.h"
#include "rom_crc.h"
#include "rom_drbg.h"
#include "rom_sideload.h"
#include "rom_keymgmt.h"
#include "rom_kmcsr.h"
#include "rom_otp.h"
#include "rom_persist.h"
#include "rom_handover.h"
#include "rom_secutil.h"
#include "key_manager_fw.h"

/**
 * @brief When set, all three handover commands (0x10-0x12) return FAILURE.
 *
 * Set by CMD_EXEC_ROM to commit the KM to ROM execution for this warm-reset
 * epoch.  Cleared by crt0 on every warm reset via .bss zeroing.
 */
static uint8_t rom_handover_disabled;

/**
 * @brief Validates command payload length.
 *
 * @param payload_len Received payload length in words.
 * @param expected_len Required payload length in words.
 * @return Success on match, otherwise `ROM_KM_RC_INVALID_LEN` with
 *     `return_arg = payload_len`.
 */
static rom_km_cmd_result_t rom_cmd_validate_payload_length(uint8_t payload_len,
                                                           uint8_t expected_len) {
    if (payload_len != expected_len)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_LEN, 1, (uint32_t)payload_len};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 0, 0};
}

/**
 * @brief Dispatches one command to its handler.
 *
 * Performs command-specific payload-length checks before calling the
 * corresponding typed handler.
 *
 * @param cmd_id Command identifier (`ROM_KM_CMD_*`).
 * @param cmd_seq Command sequence number (forwarded to handover handlers for direct response).
 * @param payload_len Payload length in 32-bit words.
 * @param payload Payload pointer, or `NULL` when `payload_len == 0`.
 * @return Handler result containing return code and optional argument.
 */
rom_km_cmd_result_t rom_cmd_dispatch(uint8_t cmd_id, uint8_t cmd_seq, uint8_t payload_len,
                                     const uint32_t *payload) {
    rom_km_cmd_result_t vr;

    switch (cmd_id) {
    case ROM_KM_CMD_HW_VER:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_hw_ver();
    case ROM_KM_CMD_ROM_VER:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_rom_ver();
    case ROM_KM_CMD_SRAM_VER:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_sram_ver();
    case ROM_KM_CMD_STAT:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_stat();
    case ROM_KM_CMD_RECOV_ACK:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_recov_ack();
    case ROM_KM_CMD_EXEC_ROM:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_exec_rom();
    case ROM_KM_CMD_SRAM_LOAD_EXEC:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_sram_load_exec(cmd_seq, (const rom_km_cmd_sram_load_exec_args_t *)payload);
    case ROM_KM_CMD_SRAM_EXEC:
        vr = rom_cmd_validate_payload_length(payload_len, 0);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_sram_exec(cmd_seq);
    case ROM_KM_CMD_KEY_GENERATE:
        vr = rom_cmd_validate_payload_length(payload_len, 2);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_key_generate((const rom_km_cmd_key_generate_args_t *)payload);
    case ROM_KM_CMD_KEY_REVOKE:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_key_revoke((const rom_km_cmd_key_revoke_args_t *)payload);
    case ROM_KM_CMD_KEY_TRANSFER:
        vr = rom_cmd_validate_payload_length(payload_len, 2);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_key_transfer((const rom_km_cmd_key_transfer_args_t *)payload);
    case ROM_KM_CMD_ENGINE_SHRED:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_engine_shred((const rom_km_cmd_engine_shred_args_t *)payload);
    case ROM_KM_CMD_KEY_LOAD:
        /* Variable-length command: no fixed-length pre-check; the length is
         * validated inside rom_cmd_key_load against KEY_SIZE. */
        return rom_cmd_key_load(payload_len, payload);
    case ROM_KM_CMD_ABR_SK_TRANSFER:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_abr_sk_transfer((const rom_km_cmd_abr_sk_transfer_args_t *)payload);
    case ROM_KM_CMD_OTP_READ_LOCK_COLD:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_otp_read_lock_cold((const rom_km_cmd_otp_read_lock_cold_args_t *)payload);
    default:
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_CMD, 0, 0};
    }
}

/**
 * @brief Returns KM hardware version.
 * @return Success with packed version value.
 */
rom_km_cmd_result_t rom_cmd_hw_ver(void) {
    rom_km_version_ret_t ret = {.raw = rom_kmcsr_version_read()};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Returns ROM firmware version.
 * @return Success with packed `major.minor.patch`.
 */
rom_km_cmd_result_t rom_cmd_rom_ver(void) {
    rom_km_version_ret_t ret = {.major = ROM_KM_ROM_VERSION_MAJOR,
                                .minor = ROM_KM_ROM_VERSION_MINOR,
                                .patch = ROM_KM_ROM_VERSION_PATCH};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Handles SRAM version query.
 * @return Always failure: the ROM carries no SRAM firmware version.
 */
rom_km_cmd_result_t rom_cmd_sram_ver(void) {
    return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};
}

/**
 * @brief Returns current recoverable-error status.
 * @return Success with packed status value.
 */
rom_km_cmd_result_t rom_cmd_stat(void) {
    rom_km_stat_ret_t ret = {.recoverable_err = rom_kmcsr_recoverable_err_bit_read() & 1u};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Acknowledges and clears recoverable-error state.
 * @return Success with no return argument.
 */
rom_km_cmd_result_t rom_cmd_recov_ack(void) {
    rom_kmcsr_recoverable_err_bit_write(0);
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 0, 0};
}

/**
 * @brief Generates a new key and returns its handle.
 *
 * @param args Parsed command payload.
 * @return Success with key handle and echoed key metadata.
 */
rom_km_cmd_result_t rom_cmd_key_generate(const rom_km_cmd_key_generate_args_t *args) {
    if (args->req_size > 127u) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    if (args->dest_valid == 0 || (args->dest_valid & ~(uint32_t)ROM_KM_DEST_VALID_MASK))
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    uint8_t key_size = (uint8_t)args->req_size;
    rom_km_dest_bits_t dest_valid = {.raw = (uint8_t)args->dest_valid};

    uint8_t handle;
    int rc = rom_generate_key(key_size, dest_valid, &handle);
    if (rc < 0) /* -1: slot-fit/KPV failure; -2: handle exhaustion */
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_key_generate_ret_t ret = {
        .key_handle = handle, .req_size = args->req_size & 0x7Fu, .dest_valid = dest_valid.raw};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Revokes a key handle.
 *
 * @param args Parsed command payload.
 * @return Success with revoked handle value.
 */
rom_km_cmd_result_t rom_cmd_key_revoke(const rom_km_cmd_key_revoke_args_t *args) {
    if (args->handle > ROM_KM_MAX_KEY_HANDLES || args->handle == ROM_KM_KEY_HANDLE_NULL)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    int rc = rom_revoke_key((uint8_t)args->handle);
    if (rc < 0) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_handle_ret_t ret = {.key_handle = args->handle & 0xFFu};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Transfers a key to one or more destination engines.
 *
 * @param args Parsed command payload.
 * @return Success with handle and destination mask.
 */
rom_km_cmd_result_t rom_cmd_key_transfer(const rom_km_cmd_key_transfer_args_t *args) {
    if (args->handle > ROM_KM_MAX_KEY_HANDLES || args->handle == ROM_KM_KEY_HANDLE_NULL)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    if (args->dest_engines == 0 || (args->dest_engines & ~(uint32_t)ROM_KM_DEST_VALID_MASK))
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    rom_km_dest_bits_t dest_engines = {.raw = (uint8_t)args->dest_engines};

    int rc = rom_transfer_key((uint8_t)args->handle, dest_engines);
    if (rc < 0) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_key_transfer_ret_t ret = {.key_handle = args->handle & 0xFFu,
                                     .dest_engine = dest_engines.raw};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Shreds sideload keys in selected crypto engines.
 *
 * @param args Parsed command payload.
 * @return Success with destination mask.
 */
rom_km_cmd_result_t rom_cmd_engine_shred(const rom_km_cmd_engine_shred_args_t *args) {
    if (args->dest == 0 || (args->dest & ~(uint32_t)ROM_KM_DEST_VALID_MASK))
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    rom_km_dest_bits_t dest = {.raw = (uint8_t)args->dest};

    if (dest.hmac_sha2) rom_hmac_shred_key(&rom_prng_state, 1);
    if (dest.kmac_sha3) rom_kmac_shred_key(&rom_prng_state, 1);
    if (dest.aes) rom_aes_shred_key(&rom_prng_state, 1);
    if (dest.otbn) rom_otbn_shred_key(&rom_prng_state, 1);
    if (dest.abr_mldsa_seed) rom_abr_mldsa_seed_shred_key(&rom_prng_state, 1);
    if (dest.abr_mlkem_seed_d) rom_abr_mlkem_seed_d_shred_key(&rom_prng_state, 1);
    if (dest.abr_mlkem_seed_z) rom_abr_mlkem_seed_z_shred_key(&rom_prng_state, 1);
    if (dest.abr_mlkem_msg) rom_abr_mlkem_msg_shred_key(&rom_prng_state, 1);

    rom_km_engine_shred_ret_t ret = {.dest_engine = dest.raw};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Loads SEP-supplied key material into the KPV via mailbox (CMD_KEY_LOAD 0x26).
 *
 * Validates payload in strict word order:
 *   Step A: payload_len < 3                     → invalid_arg, arg=0
 *   Step B: payload[0] & ~0x7F (KEY_SIZE rsvd)  → invalid_arg, arg=0
 *   Step C: key_size+3 != payload_len            → invalid_arg, arg=0
 *   Step D: payload[1] & ~0xFF (DEST rsvd[31:8]) → invalid_arg, arg=1
 *   Step E: dv==0                                → invalid_arg, arg=1
 *   Step F: rom_load_key() → failure (no arg) on slot-fit or handle exhaustion
 *
 * @param payload_len Number of 32-bit payload words received.
 * @param payload     Payload words (word0=KEY_SIZE, word1=DEST_VALID, words2..N=KEY_DATA).
 * @return Command result.
 */
rom_km_cmd_result_t rom_cmd_key_load(uint8_t payload_len, const uint32_t *payload) {
    /* Step A: need at least KEY_SIZE + DEST_VALID + 1 KEY_DATA word. */
    if (payload_len < 3u) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Step B: KEY_SIZE reserved bits [31:7] must be zero. */
    if (payload[0] & ~0x0000007Fu) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Step C: verify actual payload length matches KEY_SIZE+3. */
    uint8_t key_size = (uint8_t)(payload[0] & 0x7Fu);
    if ((uint32_t)payload_len != (uint32_t)key_size + 3u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Step D: DEST_VALID reserved bits [31:8] must be zero. */
    if (payload[1] & ~0x000000FFu) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    /* Step E: DEST_VALID must be non-zero and have no bits above [7] set. */
    uint8_t dv = (uint8_t)(payload[1] & 0xFFu);
    if (dv == 0u) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    /* Step F: allocate slots, write key, register handle. */
    rom_km_dest_bits_t dest_valid = {.raw = dv};
    uint8_t handle;
    int rc = rom_load_key(key_size, dest_valid, &payload[2], &handle);
    if (rc < 0) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    /* Success: echo KEY_HANDLE, REQ_SIZE, and DEST_VALID. */
    rom_km_key_generate_ret_t ret = {
        .key_handle = handle, .req_size = key_size & 0x7Fu, .dest_valid = dv};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Capture the ML-KEM shared key from Adams Bridge and store it in KPV.
 *
 * Validates that a shared key is available (KEY_VALID), consumes it via
 * rom_abr_mlkem_sharedkey_read() (which clears KEY_VALID and zeroizes the
 * source registers), stores it in the KPV under SEP's chosen dest_valid, and
 * returns the new key handle.
 *
 * Error conditions:
 *   - DEST_VALID reserved bits [31:8] non-zero → INVALID_ARG, arg=0
 *   - DEST_VALID == 0 or bits above [7] set    → INVALID_ARG, arg=0
 *   - KEY_VALID not set (no key ready)         → FAILURE
 *   - rom_load_key() fails                     → FAILURE
 *
 * @param args Parsed command payload.
 * @return Command result with key handle on success.
 */
rom_km_cmd_result_t rom_cmd_abr_sk_transfer(const rom_km_cmd_abr_sk_transfer_args_t *args) {
    /* Validate reserved bits [31:8]. */
    if (args->dest_valid & ~0x000000FFu) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    uint8_t dv = (uint8_t)(args->dest_valid & 0xFFu);
    if (dv == 0u || (dv & ~(uint8_t)ROM_KM_DEST_VALID_MASK))
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Reject if Adams Bridge has not yet posted a valid shared key. */
    if (!ROM_ABR_MLKEM_SK_CTRL_REG.f.key_valid)
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    /* Consume the shared key: reads KEY[0..7], clears KEY_VALID, zeroizes source. */
    uint32_t key_buf[ROM_KM_ABR_WORDS_PER_SHARE];
    rom_abr_mlkem_sharedkey_read(key_buf);

    /* Store in KPV; key_size = words - 1 = 7. */
    rom_km_dest_bits_t dest_valid = {.raw = dv};
    uint8_t handle;
    int rc = rom_load_key((uint8_t)(ROM_KM_ABR_WORDS_PER_SHARE - 1u), dest_valid, key_buf, &handle);
    rom_secure_memzero(key_buf, sizeof(key_buf));

    if (rc < 0) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_handle_ret_t ret = {.key_handle = handle};
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Set cold-reset-domain OTP read-lock bits (CMD_OTP_READ_LOCK_COLD 0x28).
 *
 * Validates that no reserved bits ([31:6]) are set in LOCK_BITS, then applies
 * the bits to OTP_READ_LOCK_COLD via the triple-write convention and echoes the
 * resulting register value.  Bits are write-1-only (woset) and survive warm
 * reset; only cold reset clears them.
 *
 * @param args Parsed command payload (word 0 = LOCK_BITS).
 * @return Success with return_arg = OTP_READ_LOCK_COLD value after write,
 *         or ROM_KM_RC_INVALID_ARG if reserved bits are set.
 */
rom_km_cmd_result_t rom_cmd_otp_read_lock_cold(const rom_km_cmd_otp_read_lock_cold_args_t *args) {
    if (args->lock_bits & ~ROM_KM_OTP_READ_LOCK_COLD_VALID_MASK)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, args->lock_bits};

    rom_otp_set_read_lock_cold(args->lock_bits);

    uint32_t result = ROM_OTP_READ_LOCK_COLD_REG.w;
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, result};
}

/*===========================================================================
 * Handover Command Handlers (0x10-0x12)
 *===========================================================================*/

/**
 * @brief Commit KM to ROM execution and inhibit future handover commands (CMD_EXEC_ROM 0x10).
 * @return Success.
 */
rom_km_cmd_result_t rom_cmd_exec_rom(void) {
    if (rom_handover_disabled) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_handover_disabled = 1;
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 0, 0};
}

/**
 * @brief Accept firmware image, load to SRAM, and execute (CMD_SRAM_LOAD_EXEC 0x11).
 *
 * On validation failure returns an error result; the dispatcher's send_resp_cmd()
 * path sends the response normally.  On validation success, rom_handover_load_and_exec()
 * sends its own RESP_CMD confirmation before streaming the image, then never returns.
 *
 * @param cmd_seq Sequence number echo for the direct confirmation response.
 * @param args    Parsed payload; FW_WORDS[15:0] must be non-zero; RESERVED[31:16] must be 0.
 * @return Error result on validation failure; never returns on success.
 */
rom_km_cmd_result_t rom_cmd_sram_load_exec(uint8_t cmd_seq,
                                           const rom_km_cmd_sram_load_exec_args_t *args) {
    if (rom_handover_disabled) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    /* Reserved bits [31:16] must be zero. */
    if (args->fw_words & ~0x0000FFFFu) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    uint32_t fw_words = args->fw_words & 0x0000FFFFu;

    if (fw_words == 0u) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Static bounds check.  __km_fw_load_limit is a region-aligned linker symbol
     * placed below the worst-case ROM stack (STACK - __rom_max_stack, rounded
     * down to an SRAM write-lock region).  Because it is fixed across boots, a
     * warm-reset CMD_SRAM_EXEC restart can never let the ROM stack descend into
     * the loaded image, and the image and ROM stack never share a lock region. */
    uint32_t limit = (uint32_t)(uintptr_t)__km_fw_load_limit;

    /* Image must fit strictly below the worst-case-stack-aligned boundary. */
    if (ROM_KM_SRAM_BASE + fw_words * 4u > limit)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    rom_handover_load_and_exec(cmd_seq, fw_words, limit);
    __builtin_unreachable();
}

/**
 * @brief Jump to pre-loaded mutable firmware (CMD_SRAM_EXEC 0x12).
 *
 * On validation failure returns an error result.  On success sends a direct
 * RESP_CMD and executes the handover sequence; never returns.
 *
 * @param cmd_seq Sequence number echo for the direct RESP_CMD.
 * @return Error result on validation failure; never returns on success.
 */
rom_km_cmd_result_t rom_cmd_sram_exec(uint8_t cmd_seq) {
    if (rom_handover_disabled) return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    uint32_t fw_size = rom_persist_get_sram_fw_size();
    if (fw_size == 0u) return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 0, 0};

    rom_handover_exec_existing(cmd_seq, fw_size);
    __builtin_unreachable();
}
