/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_xfer_err.c
 * @brief Key transfer error cases test
 *
 * Boots the KM firmware, generates a key with dest_valid = AES only,
 * then tests three transfer failure paths:
 *   1. Transfer to OTBN (not in dest_valid) → FAILURE
 *   2. Transfer with handle = 0 (null)      → INVALID_ARG
 *   3. Transfer with handle = 0xFF (absent)  → FAILURE
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_xfer_err
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
    uint32_t word;
    if (!tb_sep_mbox_read(&word, 5000)) TEST_FAIL("Failed to read response header");
    rhdr->raw = word;

    uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&word, 3);
    TEST_ASSERT_EQ(rhdr->header_crc8, exp_crc, "resp header CRC");
    TEST_ASSERT_EQ(rhdr->id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    if (!tb_sep_mbox_read(seq_echo, 5000)) TEST_FAIL("Failed to read seq echo");
    if (!tb_sep_mbox_read(cmd_echo, 5000)) TEST_FAIL("Failed to read cmd echo");

    uint32_t rc_word;
    if (!tb_sep_mbox_read(&rc_word, 5000)) TEST_FAIL("Failed to read return code");
    *rc = (int8_t)(rc_word & 0xFF);

    if (rhdr->payload_len >= 4) {
        if (!tb_sep_mbox_read(arg, 5000)) TEST_FAIL("Failed to read return arg");
    } else {
        *arg = 0;
    }

    uint32_t crc_discard;
    if (!tb_sep_mbox_read(&crc_discard, 5000)) TEST_FAIL("Failed to read payload CRC");
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xFA48u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

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
     * Generate key: 256-bit → AES only
     *
     *=================================================================*/
    uint8_t handle;

    TEST_SUBTEST_START("Setup: CMD_KEY_GENERATE 256-bit AES-only");
    {
        uint32_t payload[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen success");

        rom_km_key_generate_ret_t gen_ret = {.raw = arg};
        handle = gen_ret.key_handle;
        TEST_ASSERT_NE(handle, 0u, "handle non-zero");
        TEST_LOG("  generated handle=%u", handle);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 1: Transfer to OTBN (not in dest_valid) → FAILURE
     *
     * Key was generated with dest_valid = AES only; OTBN is not
     * permitted, so rom_transfer_key checks (dest_engines & ~dest_valid)
     * and returns -1.
     *=================================================================*/
    TEST_SUBTEST_START("Transfer to OTBN (not in dest_valid)");
    {
        uint32_t payload[2] = {(uint32_t)handle, (rom_km_dest_bits_t){.otbn = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "xfer to non-permitted dest → FAILURE");
        TEST_LOG("  OTBN transfer correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 2: Transfer with handle = 0 (null) → INVALID_ARG
     *
     * The command handler rejects ROM_KM_KEY_HANDLE_NULL (0) before
     * calling rom_transfer_key.
     *=================================================================*/
    TEST_SUBTEST_START("Transfer with null handle");
    {
        uint32_t payload[2] = {(uint32_t)ROM_KM_KEY_HANDLE_NULL,
                               (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "null handle → INVALID_ARG");
        TEST_LOG("  null handle correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 3: Transfer with handle = 0xFF (non-existent) → FAILURE
     *
     * Handle 0xFF was never allocated, so rom_check_key / keyreg
     * lookup fails and rom_transfer_key returns -1.
     *=================================================================*/
    TEST_SUBTEST_START("Transfer with non-existent handle 0xFF");
    {
        uint32_t payload[2] = {0xFFu, (rom_km_dest_bits_t){.aes = 1}.raw};

        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, payload, 2);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "non-existent handle → FAILURE");
        TEST_LOG("  handle 0xFF correctly rejected");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
