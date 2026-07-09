/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_exec_rom.c
 * @brief CMD_EXEC_ROM: success on first call; subsequent handover commands fail.
 *
 * Verifies:
 *   1. CMD_EXEC_ROM returns RESP_CMD success on first call.
 *   2. A second CMD_EXEC_ROM in the same epoch returns FAILURE.
 *   3. CMD_SRAM_LOAD_EXEC issued after CMD_EXEC_ROM returns FAILURE
 *      (no image is requested; no handover occurs).
 *   4. CMD_SRAM_EXEC issued after CMD_EXEC_ROM returns FAILURE.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_exec_rom
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"

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

/**
 * @brief Write a header-only (payload_len == 0) command frame and process it.
 */
static void send_no_payload_cmd(uint8_t cmd_id) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = 0;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write_separator_write(1, 5000))
        TEST_FAIL("separator write failed for cmd 0x%02X", (unsigned)cmd_id);
    if (!tb_sep_mbox_write(hdr.raw, 5000))
        TEST_FAIL("header write failed for cmd 0x%02X", (unsigned)cmd_id);

    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

/**
 * @brief Write a 1-word payload command frame and process it.
 */
static void send_one_word_cmd(uint8_t cmd_id, uint32_t payload_word) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = 1;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
    if (!tb_sep_mbox_write(payload_word, 5000)) TEST_FAIL("payload write failed");
    uint32_t crc = rom_crc32c((const uint8_t *)&payload_word, 4);
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");

    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

/**
 * @brief Read RESP_CMD and return the return code.
 */
static int8_t read_resp_rc(uint8_t expected_cmd_id) {
    uint32_t hdr_word;
    if (!tb_sep_mbox_read(&hdr_word, 5000))
        TEST_FAIL("no response header for cmd 0x%02X", (unsigned)expected_cmd_id);

    rom_km_msg_header_t rhdr;
    rhdr.raw = hdr_word;
    TEST_ASSERT_EQ(rhdr.id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    uint32_t seq_e, cmd_e, rc_w;
    if (!tb_sep_mbox_read(&seq_e, 5000)) TEST_FAIL("no seq_echo");
    if (!tb_sep_mbox_read(&cmd_e, 5000)) TEST_FAIL("no cmd_echo");
    if (!tb_sep_mbox_read(&rc_w, 5000)) TEST_FAIL("no rc word");

    TEST_ASSERT_EQ(seq_e & 0xFFu, (uint32_t)cmd_seq, "seq echo");
    TEST_ASSERT_EQ(cmd_e & 0xFFu, (uint32_t)expected_cmd_id, "cmd echo");

    /* optional return arg */
    uint32_t payload_words[4] = {seq_e, cmd_e, rc_w, 0};
    if (rhdr.payload_len == 4u) {
        if (!tb_sep_mbox_read(&payload_words[3], 5000)) TEST_FAIL("no return arg");
    }

    /* CRC */
    uint32_t crc_word;
    if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("no payload CRC");
    TEST_ASSERT_EQ(crc_word,
                   rom_crc32c((const uint8_t *)payload_words, (uint32_t)rhdr.payload_len * 4u),
                   "payload CRC");

    cmd_seq++;
    return (int8_t)(rc_w & 0xFFu);
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1000000)) TEST_FAIL("timeout set failed");

    if (!tb_drbg_set_seed(0xE001u, 5000)) TEST_FAIL("drbg set seed failed");

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
    }

    cmd_seq = 0;

    /*=================================================================
     * Test 1: CMD_EXEC_ROM → success
     *=================================================================*/
    TEST_SUBTEST_START("CMD_EXEC_ROM → success");
    {
        send_no_payload_cmd(ROM_KM_CMD_EXEC_ROM);
        int8_t rc = read_resp_rc(ROM_KM_CMD_EXEC_ROM);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "exec_rom first call");
        TEST_LOG("  CMD_EXEC_ROM returned SUCCESS");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 2: CMD_EXEC_ROM again → FAILURE (flag already set)
     *=================================================================*/
    TEST_SUBTEST_START("CMD_EXEC_ROM repeat → FAILURE");
    {
        send_no_payload_cmd(ROM_KM_CMD_EXEC_ROM);
        int8_t rc = read_resp_rc(ROM_KM_CMD_EXEC_ROM);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "exec_rom second call returns FAILURE");
        TEST_LOG("  CMD_EXEC_ROM repeat returned FAILURE");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 3: CMD_SRAM_LOAD_EXEC → FAILURE (inhibited by exec_rom)
     *=================================================================*/
    TEST_SUBTEST_START("CMD_SRAM_LOAD_EXEC after exec_rom → FAILURE");
    {
        /* FW_WORDS = 1; handler should return FAILURE before any handover. */
        send_one_word_cmd(ROM_KM_CMD_SRAM_LOAD_EXEC, 1u);
        int8_t rc = read_resp_rc(ROM_KM_CMD_SRAM_LOAD_EXEC);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "sram_load_exec inhibited by exec_rom");
        TEST_LOG("  CMD_SRAM_LOAD_EXEC returned FAILURE (inhibited)");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 4: CMD_SRAM_EXEC → FAILURE (inhibited)
     *=================================================================*/
    TEST_SUBTEST_START("CMD_SRAM_EXEC after exec_rom → FAILURE");
    {
        send_no_payload_cmd(ROM_KM_CMD_SRAM_EXEC);
        int8_t rc = read_resp_rc(ROM_KM_CMD_SRAM_EXEC);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "sram_exec inhibited by exec_rom");
        TEST_LOG("  CMD_SRAM_EXEC returned FAILURE (inhibited)");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
