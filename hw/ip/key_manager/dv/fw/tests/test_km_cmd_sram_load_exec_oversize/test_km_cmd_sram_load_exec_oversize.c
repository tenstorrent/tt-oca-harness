/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_sram_load_exec_oversize.c
 * @brief CMD_SRAM_LOAD_EXEC: oversize FW_WORDS → INVALID_ARG, no image transfer.
 *
 * Sends CMD_SRAM_LOAD_EXEC with FW_WORDS larger than the available image load
 * area (0xFFFF words ≈ 256 KB, far beyond the 16 KB SRAM).  Verifies the
 * command returns ROM_KM_RC_INVALID_ARG without reading any image words from
 * the mailbox.
 *
 * Also verifies zero FW_WORDS returns INVALID_ARG.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_sram_load_exec_oversize
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

static void send_load_exec(uint32_t fw_words) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = ROM_KM_CMD_SRAM_LOAD_EXEC;
    hdr.payload_len = 1;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
    if (!tb_sep_mbox_write(fw_words, 5000)) TEST_FAIL("payload write failed");
    uint32_t crc = rom_crc32c((const uint8_t *)&fw_words, 4);
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");

    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

static int8_t read_resp_rc(void) {
    uint32_t hdr_word;
    if (!tb_sep_mbox_read(&hdr_word, 5000)) TEST_FAIL("no response header");
    rom_km_msg_header_t rhdr;
    rhdr.raw = hdr_word;
    TEST_ASSERT_EQ(rhdr.id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    uint32_t pwords[4] = {0};
    for (uint8_t i = 0; i < rhdr.payload_len && i < 4u; i++) {
        if (!tb_sep_mbox_read(&pwords[i], 5000)) TEST_FAIL("no payload word %u", (unsigned)i);
    }
    uint32_t crc_word;
    if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("no payload CRC");
    TEST_ASSERT_EQ(crc_word, rom_crc32c((const uint8_t *)pwords, (uint32_t)rhdr.payload_len * 4u),
                   "payload CRC");

    TEST_ASSERT_EQ(pwords[0] & 0xFFu, (uint32_t)cmd_seq, "seq echo");
    TEST_ASSERT_EQ(pwords[1] & 0xFFu, (uint32_t)ROM_KM_CMD_SRAM_LOAD_EXEC, "cmd echo");

    cmd_seq++;
    return (int8_t)(pwords[2] & 0xFFu);
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000)) TEST_FAIL("timeout set failed");

    if (!tb_drbg_set_seed(0xE002u, 5000)) TEST_FAIL("drbg seed failed");

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
    }

    cmd_seq = 0;

    /*=================================================================
     * Test 1: FW_WORDS = 0 → INVALID_ARG
     *=================================================================*/
    TEST_SUBTEST_START("FW_WORDS=0 → INVALID_ARG");
    {
        send_load_exec(0u);
        int8_t rc = read_resp_rc();
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "zero fw_words rejected");
        TEST_LOG("  FW_WORDS=0 returned INVALID_ARG");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 2: FW_WORDS = 0xFFFF (65535 words = 256 KB) → INVALID_ARG
     * This is larger than the entire 16 KB SRAM; always rejected.
     *=================================================================*/
    TEST_SUBTEST_START("FW_WORDS=0xFFFF (oversize) → INVALID_ARG");
    {
        send_load_exec(0xFFFFu);
        int8_t rc = read_resp_rc();
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "oversize fw_words rejected");
        TEST_LOG("  FW_WORDS=0xFFFF returned INVALID_ARG (no image transferred)");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Test 3: Reserved bits in payload set → INVALID_ARG
     *=================================================================*/
    TEST_SUBTEST_START("Reserved bits [31:16] set → INVALID_ARG");
    {
        /* Bits [31:16] must be zero per spec. */
        send_load_exec(0xABCD0001u);
        int8_t rc = read_resp_rc();
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "reserved bits rejected");
        TEST_LOG("  Reserved bits in FW_WORDS word returned INVALID_ARG");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
