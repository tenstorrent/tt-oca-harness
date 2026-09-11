/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_xfer.c
 * @brief Key transfer success test
 *
 * Boots the KM firmware, generates a key with dest_valid = AES|HMAC,
 * then transfers it to each engine individually.  Verifies:
 *   1. CMD_KEY_GENERATE succeeds and returns a non-zero handle
 *   2. CMD_KEY_TRANSFER to AES succeeds
 *   3. CMD_KEY_TRANSFER to HMAC succeeds (same handle)
 *
 * Payload format for CMD_KEY_TRANSFER (2 words): word0 = KEY_HANDLE, word1 = DEST_ENGINE.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_xfer
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/*===========================================================================
 * Helpers
 *===========================================================================*/

static uint8_t cmd_seq;

static void send_cmd_with_payload(uint8_t cmd_id, const uint32_t *payload, uint8_t payload_len) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = payload_len;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");

    for (uint8_t i = 0; i < payload_len; i++) {
        if (!tb_sep_mbox_write(payload[i], 5000)) TEST_FAIL("payload write %u failed", (unsigned)i);
    }

    uint32_t crc = rom_crc32c((const uint8_t *)payload, payload_len * 4);
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");
}

static void process_and_drain(void) {
    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

static void read_resp_cmd(rom_km_msg_header_t *rhdr, uint32_t *seq_echo, uint32_t *cmd_echo,
                          int8_t *rc, uint32_t *arg) {
    uint32_t payload_words[4] = {0};
    uint32_t word;
    if (!tb_sep_mbox_read(&word, 5000)) TEST_FAIL("Failed to read response header");
    rhdr->raw = word;

    uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&word, 3);
    TEST_ASSERT_EQ(rhdr->header_crc8, exp_crc, "resp header CRC");
    TEST_ASSERT_EQ(rhdr->id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    if (!tb_sep_mbox_read(seq_echo, 5000)) TEST_FAIL("Failed to read seq echo");
    payload_words[0] = *seq_echo;
    if (!tb_sep_mbox_read(cmd_echo, 5000)) TEST_FAIL("Failed to read cmd echo");
    payload_words[1] = *cmd_echo;

    uint32_t rc_word;
    if (!tb_sep_mbox_read(&rc_word, 5000)) TEST_FAIL("Failed to read return code");
    *rc = (int8_t)(rc_word & 0xFF);
    payload_words[2] = rc_word;

    if (rhdr->payload_len >= 4) {
        if (!tb_sep_mbox_read(arg, 5000)) TEST_FAIL("Failed to read return arg");
        payload_words[3] = *arg;
    } else {
        *arg = 0;
    }

    uint32_t crc_word;
    if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("Failed to read payload CRC");
    TEST_ASSERT(rhdr->payload_len == 3u || rhdr->payload_len == 4u, "resp payload_len=%u",
                (unsigned)rhdr->payload_len);
    TEST_ASSERT_EQ(crc_word,
                   rom_crc32c((const uint8_t *)payload_words, (uint32_t)rhdr->payload_len * 4u),
                   "resp payload CRC");
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xBEEFu, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
        rom_km_msg_header_t rdy;
        rdy.raw = ready;
        TEST_ASSERT_EQ(rdy.id, (uint32_t)ROM_KM_RESP_KM_READY, "boot response id");
    }

    cmd_seq = 0;

    /*=================================================================
     * Generate key: 256-bit → AES|HMAC
     *
     * payload[0] = req_size   = 7 (words minus one: 8 × 32 = 256 bits)
     * payload[1] = dest_valid = AES|HMAC bitmask
     *=================================================================*/
    uint8_t handle;

    TEST_SUBTEST_START("CMD_KEY_GENERATE 256-bit AES|HMAC");
    {
        uint32_t payload[2] = {7u, (rom_km_dest_bits_t){.aes = 1, .hmac_sha2 = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "keygen seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_GENERATE, "keygen cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen success");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "keygen has return_arg");

        rom_km_key_generate_ret_t ret = {.raw = arg};
        handle = ret.key_handle;

        TEST_ASSERT_NE(handle, 0u, "handle non-zero");
        TEST_ASSERT_EQ(ret.req_size, 7u, "REQ_SIZE matches");
        uint32_t expect_dest = (rom_km_dest_bits_t){.aes = 1, .hmac_sha2 = 1}.raw;
        TEST_ASSERT_EQ(ret.dest_valid, expect_dest, "dest_valid matches");

        TEST_LOG("  handle=%u req_size=%u dest=0x%02X", handle, ret.req_size, ret.dest_valid);
        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /* Transfer to AES (2 words: handle, DEST_ENGINE) */
    TEST_SUBTEST_START("CMD_KEY_TRANSFER to AES");
    {
        uint32_t payload[2] = {(uint32_t)handle, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "xfer AES seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_TRANSFER, "xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "xfer AES success");
        TEST_LOG("  transfer to AES ok, arg=0x%08X", arg);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /* Transfer to HMAC (same handle) */
    TEST_SUBTEST_START("CMD_KEY_TRANSFER to HMAC");
    {
        uint32_t payload[2] = {(uint32_t)handle, (rom_km_dest_bits_t){.hmac_sha2 = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "xfer HMAC seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_TRANSFER, "xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "xfer HMAC success");
        TEST_LOG("  transfer to HMAC ok, arg=0x%08X", arg);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
