/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_revoke.c
 * @brief Key revocation test
 *
 * Boots the KM firmware, generates a key, verifies it is usable via
 * transfer, then revokes it and confirms the handle is invalidated.
 *
 * Test sequence:
 *   1. CMD_KEY_GENERATE → success, get handle
 *   2. CMD_KEY_TRANSFER to AES → success (key is valid)
 *   3. CMD_KEY_REVOKE with handle → success
 *   4. CMD_KEY_TRANSFER with revoked handle → FAILURE
 *   5. CMD_KEY_REVOKE again on same handle → FAILURE
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_revoke
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

    if (!tb_set_timeout(400000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xD055u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

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
     * Step 1: Generate key → AES
     *=================================================================*/
    uint8_t handle;

    TEST_SUBTEST_START("Setup: CMD_KEY_GENERATE 256-bit AES");
    {
        uint32_t payload[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "keygen seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_GENERATE, "keygen cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen success");

        rom_km_key_generate_ret_t gen_ret = {.raw = arg};
        handle = gen_ret.key_handle;
        TEST_ASSERT_NE(handle, 0u, "handle non-zero");
        TEST_LOG("  generated handle=%u", handle);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 2: Transfer to AES → success (proves key is valid)
     *=================================================================*/
    TEST_SUBTEST_START("Pre-revoke: CMD_KEY_TRANSFER to AES");
    {
        uint32_t payload[2] = {(uint32_t)handle, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "pre-revoke xfer seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_TRANSFER, "pre-revoke xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "pre-revoke xfer ok");
        TEST_LOG("  pre-revoke transfer succeeded");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 3: Revoke key → success
     *
     * CMD_KEY_REVOKE payload[0] = handle (bits [7:0])
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_REVOKE");
    {
        uint32_t payload[1] = {(uint32_t)handle};

        send_cmd_with_payload(ROM_KM_CMD_KEY_REVOKE, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "revoke seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_REVOKE, "revoke cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "revoke success");
        rom_km_handle_ret_t rev_ret = {.raw = arg};
        TEST_ASSERT_EQ(rev_ret.key_handle, (uint32_t)handle, "revoke echoes handle");
        TEST_LOG("  key revoked successfully");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 4: Transfer with revoked handle → FAILURE
     *=================================================================*/
    TEST_SUBTEST_START("Post-revoke: CMD_KEY_TRANSFER → FAILURE");
    {
        uint32_t payload[2] = {(uint32_t)handle, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "post-revoke xfer seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_TRANSFER,
                       "post-revoke xfer cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "post-revoke xfer → FAILURE");
        TEST_LOG("  revoked handle transfer correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 5: Revoke again on same handle → FAILURE
     *=================================================================*/
    TEST_SUBTEST_START("Double-revoke → FAILURE");
    {
        uint32_t payload[1] = {(uint32_t)handle};

        send_cmd_with_payload(ROM_KM_CMD_KEY_REVOKE, payload, 1);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "double-revoke seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_KEY_REVOKE, "double-revoke cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "double-revoke → FAILURE");
        TEST_LOG("  double revoke correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
