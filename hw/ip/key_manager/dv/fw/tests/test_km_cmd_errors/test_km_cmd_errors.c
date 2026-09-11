/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_errors.c
 * @brief Message validation error paths test
 *
 * Tests all six message validation error paths in strict priority order:
 *   1. Bad header CRC       → ROM_KM_RC_HEADER_CRC
 *   2. Out-of-sequence      → ROM_KM_RC_CMD_NOSEQ
 *   3. Invalid command ID   → ROM_KM_RC_INVALID_CMD
 *   4. Wrong payload length → ROM_KM_RC_INVALID_LEN
 *   5. Bad payload CRC      → ROM_KM_RC_PAYLOAD_CRC
 *   6. Validation ordering  (header CRC checked before seq number)
 *
 * After boot, the firmware expects cmd_seq_num=0.  Tests that pass
 * the sequence check increment the counter; tests that fail before
 * the sequence check do not.  The test tracks the expected seq number.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_errors
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

/**
 * Send a single-word (header-only, no payload) command frame via SEP
 * mailbox.  Sets separator before the header word.
 */
static void send_header_only(rom_km_msg_header_t hdr) {
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("sep mbox write failed");
}

/**
 * Send a multi-word command frame via SEP mailbox.
 * Frame: header + payload[0..N-1] + CRC (separator on last word).
 */
static void send_frame_with_payload(rom_km_msg_header_t hdr, const uint32_t *payload,
                                    uint8_t payload_len, uint32_t crc) {
    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
    for (uint8_t i = 0; i < payload_len; i++) {
        if (!tb_sep_mbox_write(payload[i], 5000)) TEST_FAIL("payload write %u failed", (unsigned)i);
    }
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");
}

/**
 * Process the queued frame and drain the response to the outbound FIFO.
 */
static void process_and_drain(void) {
    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

/**
 * Read a RESP_CMD from the SEP outbound mailbox and extract fields.
 *
 * @param[out] rhdr      Response header.
 * @param[out] seq_echo  Echoed command sequence number.
 * @param[out] cmd_echo  Echoed command ID.
 * @param[out] rc        Return code (sign-extended to int8_t).
 * @param[out] arg       Return argument (valid only when header.payload_len >= 4).
 */
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

    if (!tb_set_timeout(1000000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(0xE77B, 5000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
    }

    /*
     * Track expected command sequence number.  Errors detected before
     * the sequence check (header CRC) leave it unchanged; errors after
     * a successful sequence match increment it.
     */
    uint8_t expected_cmd_seq = 0;

    /*=====================================================================
     * Test 1: Bad header CRC → ROM_KM_RC_HEADER_CRC
     *
     * Seq check is NOT reached, so expected_cmd_seq stays the same.
     *=====================================================================*/
    TEST_SUBTEST_START("Bad header CRC");
    {
        rom_km_msg_header_t cmd;
        cmd.seq_num = expected_cmd_seq;
        cmd.id = ROM_KM_CMD_HW_VER;
        cmd.payload_len = 0;
        cmd.header_crc8 = 0xAA; /* invalid CRC */

        send_header_only(cmd);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_HEADER_CRC, "rc = HEADER_CRC");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "has return_arg");
        /* arg contains the correctly computed CRC */
        TEST_LOG("  actual CRC=0x%02X, arg=0x%08X", (unsigned)arg & 0xFF, arg);
        /* expected_cmd_seq unchanged */
    }
    TEST_SUBTEST_PASS();

    /*=====================================================================
     * Test 2: Out-of-sequence → ROM_KM_RC_CMD_NOSEQ
     *
     * Send with wrong seq_num.  Seq check fails → expected_cmd_seq
     * does not increment.
     *=====================================================================*/
    TEST_SUBTEST_START("Out-of-sequence");
    {
        rom_km_msg_header_t cmd;
        cmd.seq_num = expected_cmd_seq + 5; /* out-of-sequence */
        cmd.id = ROM_KM_CMD_ROM_VER;
        cmd.payload_len = 0;
        cmd.header_crc8 = rom_crc8_rohc((const uint8_t *)&cmd, 3);

        send_header_only(cmd);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_CMD_NOSEQ, "rc = CMD_NOSEQ");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "has return_arg");
        TEST_ASSERT_EQ(arg & 0xFF, (uint32_t)expected_cmd_seq, "arg = next expected seq");
        /* expected_cmd_seq unchanged */
    }
    TEST_SUBTEST_PASS();

    /*=====================================================================
     * Test 3: Invalid command ID → ROM_KM_RC_INVALID_CMD
     *
     * Uses a command ID in the gap between 0x04 and 0x10 (0x05 is
     * permanently reserved and never valid).  Seq check passes, so
     * expected_cmd_seq increments.
     *=====================================================================*/
    TEST_SUBTEST_START("Invalid command ID");
    {
        rom_km_msg_header_t cmd;
        cmd.seq_num = expected_cmd_seq;
        cmd.id = 0x05; /* reserved gap: 0x05-0x0F are never valid */
        cmd.payload_len = 0;
        cmd.header_crc8 = rom_crc8_rohc((const uint8_t *)&cmd, 3);

        send_header_only(cmd);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_CMD, "rc = INVALID_CMD");
        TEST_ASSERT_EQ(cmd_e & 0xFF, 0x05u, "cmd echo = 0x05");
        expected_cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=====================================================================
     * Test 4: Wrong payload length → ROM_KM_RC_INVALID_LEN
     *
     * Header claims payload_len=2 but frame contains only header +
     * 1 payload word + CRC (3 words total).  Seq check passes.
     *=====================================================================*/
    TEST_SUBTEST_START("Wrong payload length");
    {
        rom_km_msg_header_t cmd;
        cmd.seq_num = expected_cmd_seq;
        cmd.id = ROM_KM_CMD_HW_VER;
        cmd.payload_len = 2; /* claim 2 payload words */
        cmd.header_crc8 = rom_crc8_rohc((const uint8_t *)&cmd, 3);

        /* Actually send only 1 payload word + CRC (frame = 3 words) */
        uint32_t one_word = 0xDEADBEEF;
        uint32_t crc = rom_crc32c((const uint8_t *)&one_word, 4);
        send_frame_with_payload(cmd, &one_word, 1, crc);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_LEN, "rc = INVALID_LEN");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "has return_arg");
        expected_cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=====================================================================
     * Test 5: Bad payload CRC → ROM_KM_RC_PAYLOAD_CRC
     *
     * Correct header, correct seq, valid cmd, correct payload_len,
     * but the CRC-32C word is corrupted.  Seq check passes.
     *=====================================================================*/
    TEST_SUBTEST_START("Bad payload CRC");
    {
        rom_km_msg_header_t cmd;
        cmd.seq_num = expected_cmd_seq;
        cmd.id = ROM_KM_CMD_HW_VER;
        cmd.payload_len = 1;
        cmd.header_crc8 = rom_crc8_rohc((const uint8_t *)&cmd, 3);

        uint32_t payload_word = 0xCAFEBABE;
        uint32_t bad_crc = 0x12345678; /* mismatching CRC */
        send_frame_with_payload(cmd, &payload_word, 1, bad_crc);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_PAYLOAD_CRC, "rc = PAYLOAD_CRC");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "has return_arg");

        /* arg should contain the correctly computed CRC */
        uint32_t exp_crc = rom_crc32c((const uint8_t *)&payload_word, 4);
        TEST_ASSERT_EQ(arg, exp_crc, "arg = computed CRC");
        expected_cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=====================================================================
     * Test 6: Validation ordering — header CRC checked before seq
     *
     * Send a command with BOTH a bad header CRC AND a wrong sequence
     * number.  The error response should be ROM_KM_RC_HEADER_CRC (not
     * ROM_KM_RC_CMD_NOSEQ), proving header CRC is checked first.
     *=====================================================================*/
    TEST_SUBTEST_START("Validation order: header CRC before seq");
    {
        rom_km_msg_header_t cmd;
        cmd.seq_num = expected_cmd_seq + 99; /* wrong seq */
        cmd.id = ROM_KM_CMD_STAT;
        cmd.payload_len = 0;
        cmd.header_crc8 = 0xBB; /* wrong CRC */

        send_header_only(cmd);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_HEADER_CRC, "rc = HEADER_CRC (not CMD_NOSEQ)");
        /* expected_cmd_seq unchanged since header CRC fails first */
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
