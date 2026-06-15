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
#include "key_manager_regs.h"

/**
 * @brief Validates command payload length.
 *
 * @param payload_len Received payload length in words.
 * @param expected_len Required payload length in words.
 * @return Success on match, otherwise `ROM_KM_RC_INVALID_LEN` with
 *     `return_arg = payload_len`.
 */
static rom_km_cmd_result_t rom_cmd_validate_payload_length(
    uint8_t payload_len,
    uint8_t expected_len)
{
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
 * @param payload_len Payload length in 32-bit words.
 * @param payload Payload pointer, or `NULL` when `payload_len == 0`.
 * @return Handler result containing return code and optional argument.
 */
rom_km_cmd_result_t rom_cmd_dispatch(uint8_t cmd_id, uint8_t payload_len,
                                 const uint32_t *payload)
{
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
    case ROM_KM_CMD_KPVLP_SLOT_REQ:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_kpvlp_slot_req(
            (const rom_km_cmd_slot_req_args_t *)payload);
    case ROM_KM_CMD_KPVLP_KEY_REGISTER:
        vr = rom_cmd_validate_payload_length(payload_len, 4);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_kpvlp_key_register(
            (const rom_km_cmd_kpvlp_key_register_args_t *)payload);
    case ROM_KM_CMD_KEY_GENERATE:
        vr = rom_cmd_validate_payload_length(payload_len, 2);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_key_generate(
            (const rom_km_cmd_key_generate_args_t *)payload);
    case ROM_KM_CMD_KEY_REVOKE:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_key_revoke(
            (const rom_km_cmd_key_revoke_args_t *)payload);
    case ROM_KM_CMD_KEY_TRANSFER:
        vr = rom_cmd_validate_payload_length(payload_len, 2);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_key_transfer(
            (const rom_km_cmd_key_transfer_args_t *)payload);
    case ROM_KM_CMD_ENGINE_SHRED:
        vr = rom_cmd_validate_payload_length(payload_len, 1);
        if (vr.return_code != ROM_KM_RC_SUCCESS) return vr;
        return rom_cmd_engine_shred(
            (const rom_km_cmd_engine_shred_args_t *)payload);
    case ROM_KM_CMD_KEY_LOAD:
        /* Variable-length command: skip fixed-length pre-check per R-001.
         * Length is validated inside rom_cmd_key_load against KEY_SIZE. */
        return rom_cmd_key_load(payload_len, payload);
    default:
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_CMD, 0, 0};
    }
}

/**
 * @brief Returns KM hardware version.
 * @return Success with packed version value.
 */
rom_km_cmd_result_t rom_cmd_hw_ver(void)
{
    rom_km_version_ret_t ret = { .raw = rom_kmcsr_version_read() };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Returns ROM firmware version.
 * @return Success with packed `major.minor.patch`.
 */
rom_km_cmd_result_t rom_cmd_rom_ver(void)
{
    rom_km_version_ret_t ret = {
        .major = ROM_KM_ROM_VERSION_MAJOR,
        .minor = ROM_KM_ROM_VERSION_MINOR,
        .patch = ROM_KM_ROM_VERSION_PATCH
    };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Handles SRAM version query.
 * @return Always returns failure (not implemented in ROM).
 */
rom_km_cmd_result_t rom_cmd_sram_ver(void)
{
    return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};
}

/**
 * @brief Returns current recoverable-error status.
 * @return Success with packed status value.
 */
rom_km_cmd_result_t rom_cmd_stat(void)
{
    rom_km_stat_ret_t ret = { .recoverable_err = rom_kmcsr_recoverable_err_bit_read() & 1u };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Acknowledges and clears recoverable-error state.
 * @return Success with no return argument.
 */
rom_km_cmd_result_t rom_cmd_recov_ack(void)
{
    rom_kmcsr_recoverable_err_bit_write(0);
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 0, 0};
}

/**
 * @brief Allocates KPV slots for SEP KPVLP writes.
 *
 * @param args Command payload (`slot_req` encoded as `num_slots - 1`).
 * @return Success with granted slot count and base slot index.
 */
rom_km_cmd_result_t rom_cmd_kpvlp_slot_req(const rom_km_cmd_slot_req_args_t *args)
{
    if (args->slot_req > 7u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    uint8_t num_slots = (uint8_t)(args->slot_req + 1u);

    uint8_t base_slot;
    int rc = rom_allocate_kpvlp_slot(num_slots, &base_slot);
    if (rc < 0)
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_slot_req_ret_t ret = {
        .base_slot_index = base_slot & 0x1Fu,
        .slot_grant      = args->slot_req & 0x7u
    };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Registers a SEP-loaded KPVLP key and allocates a handle.
 *
 * @param args Parsed command payload.
 * @return Success with new key handle.
 */
rom_km_cmd_result_t rom_cmd_kpvlp_key_register(
    const rom_km_cmd_kpvlp_key_register_args_t *args)
{
    if (args->base_slot > 31u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    if (args->key_size > 127u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    if (args->dest_valid == 0 || args->dest_valid > 15u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 2};

    uint8_t key_size_words = (uint8_t)(args->key_size + 1u);
    rom_km_dest_bits_t dest_valid = { .raw = (uint8_t)args->dest_valid };

    uint8_t handle;
    int rc = rom_register_kpvlp_key((uint8_t)args->base_slot, key_size_words,
                                    dest_valid, args->key_crc32, &handle);
    if (rc < 0)
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_handle_ret_t ret = { .key_handle = handle };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Generates a new key and returns its handle.
 *
 * @param args Parsed command payload.
 * @return Success with key handle and echoed key metadata.
 */
rom_km_cmd_result_t rom_cmd_key_generate(const rom_km_cmd_key_generate_args_t *args)
{
    if (args->req_size > 127u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    if (args->dest_valid == 0 || args->dest_valid > 15u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    uint8_t key_size = (uint8_t)args->req_size;
    rom_km_dest_bits_t dest_valid = { .raw = (uint8_t)args->dest_valid };

    uint8_t handle;
    int rc = rom_generate_key(key_size, dest_valid, &handle);
    if (rc < 0)  /* -1: slot-fit/KPV failure; -2: handle exhaustion */
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_key_generate_ret_t ret = {
        .key_handle = handle,
        .req_size   = args->req_size & 0x7Fu,
        .dest_valid = dest_valid.raw
    };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Revokes a key handle.
 *
 * @param args Parsed command payload.
 * @return Success with revoked handle value.
 */
rom_km_cmd_result_t rom_cmd_key_revoke(const rom_km_cmd_key_revoke_args_t *args)
{
    if (args->handle > ROM_KM_MAX_KEY_HANDLES || args->handle == ROM_KM_KEY_HANDLE_NULL)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    int rc = rom_revoke_key((uint8_t)args->handle);
    if (rc < 0)
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_handle_ret_t ret = { .key_handle = args->handle & 0xFFu };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Transfers a key to one or more destination engines.
 *
 * @param args Parsed command payload.
 * @return Success with handle and destination mask.
 */
rom_km_cmd_result_t rom_cmd_key_transfer(const rom_km_cmd_key_transfer_args_t *args)
{
    if (args->handle > ROM_KM_MAX_KEY_HANDLES || args->handle == ROM_KM_KEY_HANDLE_NULL)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    if (args->dest_engines == 0 || args->dest_engines > 15u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    rom_km_dest_bits_t dest_engines = { .raw = (uint8_t)args->dest_engines };

    int rc = rom_transfer_key((uint8_t)args->handle, dest_engines);
    if (rc < 0)
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    rom_km_key_transfer_ret_t ret = {
        .key_handle  = args->handle & 0xFFu,
        .dest_engine = dest_engines.raw
    };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Shreds sideload keys in selected crypto engines.
 *
 * @param args Parsed command payload.
 * @return Success with destination mask.
 */
rom_km_cmd_result_t rom_cmd_engine_shred(const rom_km_cmd_engine_shred_args_t *args)
{
    if (args->dest == 0 || args->dest > 15u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    rom_km_dest_bits_t dest = { .raw = (uint8_t)args->dest };

    if (dest.hmac_sha2) rom_hmac_shred_key(&rom_prng_state, 1);
    if (dest.kmac_sha3) rom_kmac_shred_key(&rom_prng_state, 1);
    if (dest.aes)       rom_aes_shred_key(&rom_prng_state, 1);
    if (dest.otbn)      rom_otbn_shred_key(&rom_prng_state, 1);

    rom_km_engine_shred_ret_t ret = { .dest_engine = dest.raw };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}

/**
 * @brief Loads SEP-supplied key material into the KPV via mailbox (CMD_KEY_LOAD 0x26).
 *
 * Validates payload in strict word order (FR-2739-015):
 *   Step A: payload_len < 3                     → invalid_arg, arg=0
 *   Step B: payload[0] & ~0x7F (KEY_SIZE rsvd)  → invalid_arg, arg=0
 *   Step C: key_size+3 != payload_len            → invalid_arg, arg=0
 *   Step D: payload[1] & ~0xFF (DEST rsvd[31:8]) → invalid_arg, arg=1
 *   Step E: dv==0 || dv & ~0x0F (DEST zero/rsvd) → invalid_arg, arg=1
 *   Step F: rom_load_key() → failure (no arg) on slot-fit or handle exhaustion
 *
 * @param payload_len Number of 32-bit payload words received.
 * @param payload     Payload words (word0=KEY_SIZE, word1=DEST_VALID, words2..N=KEY_DATA).
 * @return Command result.
 */
rom_km_cmd_result_t rom_cmd_key_load(uint8_t payload_len, const uint32_t *payload)
{
    /* Step A: need at least KEY_SIZE + DEST_VALID + 1 KEY_DATA word (FR-2739-011). */
    if (payload_len < 3u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Step B: KEY_SIZE reserved bits [31:7] must be zero (FR-2739-003). */
    if (payload[0] & ~0x0000007Fu)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Step C: verify actual payload length matches KEY_SIZE+3 (FR-2739-011). */
    uint8_t key_size = (uint8_t)(payload[0] & 0x7Fu);
    if ((uint32_t)payload_len != (uint32_t)key_size + 3u)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 0};

    /* Step D: DEST_VALID reserved bits [31:8] must be zero (FR-2739-003). */
    if (payload[1] & ~0x000000FFu)
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    /* Step E: DEST_VALID must be non-zero and have no reserved bits [7:4] set (FR-2739-012). */
    uint8_t dv = (uint8_t)(payload[1] & 0xFFu);
    if (dv == 0u || (dv & ~0x0Fu))
        return (rom_km_cmd_result_t){ROM_KM_RC_INVALID_ARG, 1, 1};

    /* Step F: allocate slots, write key, register handle (FR-2739-013, FR-2739-014). */
    rom_km_dest_bits_t dest_valid = { .raw = dv };
    uint8_t handle;
    int rc = rom_load_key(key_size, dest_valid, &payload[2], &handle);
    if (rc < 0)
        return (rom_km_cmd_result_t){ROM_KM_RC_FAILURE, 0, 0};

    /* Success: echo KEY_HANDLE, REQ_SIZE, and DEST_VALID (FR-2739-040..042). */
    rom_km_key_generate_ret_t ret = {
        .key_handle = handle,
        .req_size   = key_size & 0x7Fu,
        .dest_valid = dv
    };
    return (rom_km_cmd_result_t){ROM_KM_RC_SUCCESS, 1, ret.raw};
}
