/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Shared Key Manager (KM) mailbox client for SEP firmware tests.
 *
 * The SEP CPU talks to the production Key Manager over the SEP-visible KM
 * mailbox (KM_MAILBOX_SEP_* CSRs). Messages are framed as:
 *
 *   Word 0      : header = [CRC8_ROHC(seq,id,len) | len | id | seq]
 *   Words 1..N  : payload (0..12 words)
 *   Word N+1    : CRC-32C of the payload (only present when len != 0)
 *
 * The last word of every frame is flagged by writing the WRITE_SEPARATOR CSR
 * before the data word; inbound frames are delimited by the STATUS separator
 * bit. This client mirrors the frame sequence sep_cpu_sram_aes_sram_test drives
 * inline and is shared by the KM sideload tests.
 *
 * Command / destination encodings match hw/ip/key_manager/dv/fw
 * (rom_defs.h rom_km_cmd_id_t / rom_km_dest_bits_t).
 */

#ifndef KM_MAILBOX_H
#define KM_MAILBOX_H

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"

/* KM ROM command IDs (rom_defs.h rom_km_cmd_id_t). */
#define KM_CMD_KEY_TRANSFER 0x24u
#define KM_CMD_ENGINE_SHRED 0x25u
#define KM_CMD_KEY_LOAD 0x26u

/* KM response IDs. */
#define KM_RESP_CMD 0x00u
#define KM_RESP_READY 0x55u

/* KM destination bitmask (rom_defs.h rom_km_dest_bits_t). */
#define KM_DEST_HMAC_SHA2 0x01u
#define KM_DEST_KMAC_SHA3 0x02u
#define KM_DEST_AES 0x04u
#define KM_DEST_OTBN 0x08u
#define KM_DEST_ABR_MLDSA_SEED 0x10u
#define KM_DEST_ABR_MLKEM_D 0x20u
#define KM_DEST_ABR_MLKEM_Z 0x40u
#define KM_DEST_ABR_MLKEM_MSG 0x80u

/* STATUS register bit aliases. */
#define KM_STATUS_IN_FULL KM_MAILBOX_SEP__STATUS_REG__INBOUND_FULL_bm
#define KM_STATUS_OUT_EMPTY KM_MAILBOX_SEP__STATUS_REG__OUTBOUND_EMPTY_bm
#define KM_STATUS_OUT_SEP KM_MAILBOX_SEP__STATUS_REG__OUTBOUND_SEPARATOR_bm

/* Generous poll budget; the UVM FW_TEST_TIMEOUT is the real backstop. */
#define KM_MBOX_TIMEOUT 2000000u

/* Per-translation-unit frame sequence counters. */
static uint8_t km_cmd_seq;
static uint8_t km_resp_seq;

static uint8_t km_crc8_rohc_bytes(const uint8_t *data, uint32_t len) {
    uint8_t crc = 0xffu;

    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint32_t bit = 0; bit < 8; bit++)
            crc = (crc & 1u) ? (uint8_t)((crc >> 1) ^ 0xe0u) : (uint8_t)(crc >> 1);
    }
    return crc;
}

static uint32_t km_crc32c_words(const uint32_t *words, uint32_t count) {
    uint32_t crc = 0xffffffffu;

    for (uint32_t i = 0; i < count; i++) {
        uint32_t word = words[i];
        for (uint32_t byte = 0; byte < 4; byte++) {
            crc ^= (word >> (byte * 8u)) & 0xffu;
            for (uint32_t bit = 0; bit < 8; bit++)
                crc = (crc & 1u) ? (crc >> 1) ^ 0x82f63b78u : crc >> 1;
        }
    }
    return crc ^ 0xffffffffu;
}

static uint32_t km_header(uint8_t seq, uint8_t id, uint8_t payload_len) {
    uint8_t bytes[3] = {seq, id, payload_len};
    uint32_t crc = km_crc8_rohc_bytes(bytes, 3);

    return (crc << 24) | ((uint32_t)payload_len << 16) | ((uint32_t)id << 8) | seq;
}

static int km_wait_inbound_space(void) {
    uint32_t timeout = KM_MBOX_TIMEOUT;

    while (timeout-- != 0u) {
        if ((READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR) & KM_STATUS_IN_FULL) == 0u)
            return 0;
    }
    return -1;
}

static int km_send_frame(uint8_t id, const uint32_t *payload, uint8_t payload_len) {
    uint32_t words[16];
    uint32_t total = 1u;

    if (payload_len > 12u) return -1;

    words[0] = km_header(km_cmd_seq, id, payload_len);
    for (uint32_t i = 0; i < payload_len; i++) words[total++] = payload[i];
    if (payload_len != 0u) words[total++] = km_crc32c_words(payload, payload_len);

    for (uint32_t i = 0; i < total; i++) {
        if (km_wait_inbound_space() != 0) return -1;
        if (i == total - 1u)
            WRITE_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_SEPARATOR_BASE_ADDR, 1u);
        WRITE_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_WRITE_DATA_BASE_ADDR, words[i]);
    }
    km_cmd_seq++;
    return 0;
}

static int km_recv_frame(uint32_t *words, uint32_t capacity, uint32_t *count) {
    uint32_t timeout = KM_MBOX_TIMEOUT;
    uint32_t n = 0u;

    while (timeout-- != 0u) {
        uint32_t status = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR);

        if ((status & KM_STATUS_OUT_EMPTY) != 0u) continue;
        if (n >= capacity) return -1;

        words[n++] = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_READ_DATA_BASE_ADDR);
        status = READ_REG(SEP_TOP_KM_MAILBOX_SEP_SEP_STATUS_BASE_ADDR);
        if ((status & KM_STATUS_OUT_SEP) != 0u) {
            *count = n;
            return 0;
        }
    }
    return -1;
}

static int km_validate_frame(const uint32_t *words, uint32_t count, uint8_t expected_id,
                             const uint32_t **payload, uint8_t *payload_len) {
    uint32_t header;
    uint8_t bytes[3];
    uint8_t len;

    if (count == 0u) return -1;

    header = words[0];
    bytes[0] = (uint8_t)header;
    bytes[1] = (uint8_t)(header >> 8);
    bytes[2] = (uint8_t)(header >> 16);
    len = bytes[2];

    if ((uint8_t)(header >> 24) != km_crc8_rohc_bytes(bytes, 3)) return -1;
    if (bytes[0] != km_resp_seq || bytes[1] != expected_id) return -1;
    if (count != 1u + len + ((len != 0u) ? 1u : 0u)) return -1;
    if (len != 0u && words[1u + len] != km_crc32c_words(&words[1], len)) return -1;

    km_resp_seq++;
    *payload = &words[1];
    *payload_len = len;
    return 0;
}

/* Wait for the KM boot-complete banner (RESP_READY, no payload). */
static int km_wait_ready(void) {
    uint32_t words[8];
    uint32_t count;
    const uint32_t *payload;
    uint8_t payload_len;

    if (km_recv_frame(words, 8, &count) != 0) return -1;
    if (km_validate_frame(words, count, KM_RESP_READY, &payload, &payload_len) != 0) return -1;
    return (payload_len == 0u) ? 0 : -1;
}

/*
 * Issue a command frame and validate the RESP_CMD reply. The response payload
 * is [seq, id, status, <return arg...>]; status != 0 is a KM-reported failure.
 * On success *return_arg receives payload word 3 (0 if absent).
 */
static int km_command(uint8_t id, const uint32_t *payload, uint8_t payload_len,
                      uint32_t *return_arg) {
    uint32_t words[12];
    uint32_t count;
    const uint32_t *response;
    uint8_t response_len;
    uint8_t sent_seq = km_cmd_seq;

    if (km_send_frame(id, payload, payload_len) != 0) return -1;
    if (km_recv_frame(words, 12, &count) != 0) return -1;
    if (km_validate_frame(words, count, KM_RESP_CMD, &response, &response_len) != 0) return -1;
    if (response_len < 3u || (uint8_t)response[0] != sent_seq || (uint8_t)response[1] != id ||
        (int8_t)response[2] != 0)
        return -1;

    if (return_arg != 0) *return_arg = (response_len >= 4u) ? response[3] : 0u;
    return 0;
}

/* Release the KM out of reset via the SEP reset controller. */
static int km_release_reset(void) {
    uint32_t reset_n = READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR);

    reset_n |= SEP_RESET_CTRL__SW_RESET_N__KM_SW_RST_N_bm;
    WRITE_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR, reset_n);
    __asm__ volatile("fence" ::: "memory");
    return (READ_REG(SEP_TOP_SEP_RESET_CTRL_SW_RESET_N_BASE_ADDR) &
            SEP_RESET_CTRL__SW_RESET_N__KM_SW_RST_N_bm)
               ? 0
               : -1;
}

/*
 * Load SEP-supplied key material into the KPV and transfer it to one or more
 * destination engines' sideload ports. `key_words` is the plaintext key length
 * in 32-bit words (1..12); the KM re-masks it into XOR shares on delivery.
 * Returns 0 on success and, when handle_o != 0, stores the KPV key handle.
 */
static int km_load_and_transfer_key(const uint32_t *key, uint8_t key_words, uint8_t dest_mask,
                                    uint8_t *handle_o) {
    uint32_t load_payload[14];
    uint32_t transfer_payload[2];
    uint32_t result = 0u;

    if (key_words == 0u || key_words > 12u) return -1;

    load_payload[0] = (uint32_t)(key_words - 1u); /* KEY_SIZE = words - 1 */
    load_payload[1] = dest_mask;
    for (uint8_t i = 0; i < key_words; i++) load_payload[2u + i] = key[i];

    if (km_command(KM_CMD_KEY_LOAD, load_payload, (uint8_t)(key_words + 2u), &result) != 0)
        return -1;

    if (handle_o != 0) *handle_o = (uint8_t)result;

    transfer_payload[0] = (uint8_t)result;
    transfer_payload[1] = dest_mask;
    return km_command(KM_CMD_KEY_TRANSFER, transfer_payload, 2, &result);
}

/* Shred the sideload key(s) in the selected engine(s). */
static int km_shred_engine(uint8_t dest_mask) {
    uint32_t payload = dest_mask;
    uint32_t result;

    return km_command(KM_CMD_ENGINE_SHRED, &payload, 1, &result);
}

#endif /* KM_MAILBOX_H */
