/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_sram_exec_empty.c
 * @brief CMD_SRAM_EXEC with sram_fw_size == 0 → INVALID_ARG, no jump.
 *
 * On a cold boot, sram_fw_size is zero.  Verifies that CMD_SRAM_EXEC returns
 * ROM_KM_RC_INVALID_ARG and does not perform a handover jump.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_sram_exec_empty
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"
#include "rom_persist.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000)) TEST_FAIL("timeout set failed");

    if (!tb_drbg_set_seed(0xE003u, 5000)) TEST_FAIL("drbg seed failed");

    rom_boot_init();

    /* Discard RESP_KM_READY */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY");
    }

    /*=================================================================
     * Verify sram_fw_size == 0 on fresh (cold) boot
     *=================================================================*/
    TEST_SUBTEST_START("sram_fw_size == 0 on cold boot");
    {
        uint32_t sz = rom_persist_get_sram_fw_size();
        TEST_ASSERT_EQ(sz, 0u, "sram_fw_size cold boot");
        TEST_LOG("  sram_fw_size = 0 confirmed");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * CMD_SRAM_EXEC with sram_fw_size == 0 → INVALID_ARG
     *=================================================================*/
    TEST_SUBTEST_START("CMD_SRAM_EXEC (no firmware loaded) → INVALID_ARG");
    {
        uint8_t seq = 0;

        rom_km_msg_header_t hdr;
        hdr.seq_num = seq;
        hdr.id = ROM_KM_CMD_SRAM_EXEC;
        hdr.payload_len = 0;
        hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

        if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
        if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");

        test_delay(1000);
        rom_msg_rx_process();
        rom_isr_mailbox();

        /* Read RESP_CMD */
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
        if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("no CRC");
        TEST_ASSERT_EQ(crc_word,
                       rom_crc32c((const uint8_t *)pwords, (uint32_t)rhdr.payload_len * 4u), "CRC");

        TEST_ASSERT_EQ(pwords[0] & 0xFFu, (uint32_t)seq, "seq echo");
        TEST_ASSERT_EQ(pwords[1] & 0xFFu, (uint32_t)ROM_KM_CMD_SRAM_EXEC, "cmd echo");
        int8_t rc = (int8_t)(pwords[2] & 0xFFu);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_INVALID_ARG, "sram_exec empty → INVALID_ARG");
        TEST_LOG("  CMD_SRAM_EXEC returned INVALID_ARG (sram_fw_size=0)");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
