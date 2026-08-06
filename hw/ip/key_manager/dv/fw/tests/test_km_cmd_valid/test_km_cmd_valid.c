/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_valid.c
 * @brief T037 - Valid command transport test
 *
 * Sends CMD_HW_VER (command ID 0x00, no payload) via the SEP mailbox,
 * verifies that RESP_CMD is received with correct seq_num echo, cmd_id
 * echo, a valid header CRC, and a correct payload CRC-32C.
 *
 * CMD_HW_VER returns SUCCESS with one return argument (the HW version
 * register), so the RESP_CMD payload is 4 words:
 *   [0] seq_echo, [1] cmd_echo, [2] return_code, [3] return_arg.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_cmd_valid
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

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(0xC0DE, 5000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    rom_boot_init();

    /* --- Discard RESP_KM_READY --- */
    TEST_SUBTEST_START("Discard RESP_KM_READY");
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) {
            TEST_FAIL("No RESP_KM_READY in outbound mailbox");
        }
        rom_km_msg_header_t rdy_hdr;
        rdy_hdr.raw = ready;
        TEST_ASSERT_EQ(rdy_hdr.id, (uint32_t)ROM_KM_RESP_KM_READY, "boot response id");
    }
    TEST_SUBTEST_PASS();

    /* --- Send CMD_HW_VER and verify RESP_CMD --- */
    TEST_SUBTEST_START("CMD_HW_VER round-trip");
    {
        /* Build header: seq=0, cmd=HW_VER, payload_len=0, CRC-8 */
        rom_km_msg_header_t cmd;
        cmd.seq_num = 0;
        cmd.id = ROM_KM_CMD_HW_VER;
        cmd.payload_len = 0;
        cmd.header_crc8 = rom_crc8_rohc((const uint8_t *)&cmd, 3);

        /* Send single-word frame via SEP mailbox (separator first) */
        if (!tb_sep_mbox_write_separator_write(1, 5000)) {
            TEST_FAIL("Failed to set separator");
        }
        if (!tb_sep_mbox_write(cmd.raw, 5000)) {
            TEST_FAIL("Failed to write command");
        }

        /* Let ISR drain inbound FIFO into rx_buf */
        test_delay(1000);

        /* Process the command frame */
        rom_msg_rx_process();

        /* Trigger ISR to drain tx_buf to outbound FIFO */
        rom_isr_mailbox();

        /* Read response header from SEP outbound */
        uint32_t resp_hdr_word;
        if (!tb_sep_mbox_read(&resp_hdr_word, 5000)) {
            TEST_FAIL("No RESP_CMD in outbound mailbox");
        }
        rom_km_msg_header_t rhdr;
        rhdr.raw = resp_hdr_word;

        TEST_LOG("  RESP header: 0x%08X", resp_hdr_word);
        TEST_LOG("  id=0x%02X seq=%u len=%u crc=0x%02X", rhdr.id, rhdr.seq_num, rhdr.payload_len,
                 rhdr.header_crc8);

        TEST_ASSERT_EQ(rhdr.id, (uint32_t)ROM_KM_RESP_CMD, "Response ID");

        /* Verify response header CRC */
        uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&resp_hdr_word, 3);
        TEST_ASSERT_EQ(rhdr.header_crc8, exp_crc, "Response header CRC");

        /* Read all payload words (count from header) */
        uint8_t plen = rhdr.payload_len;
        TEST_ASSERT_EQ(plen, 4u, "payload_len");

        uint32_t pw[4] = {0};
        for (uint8_t i = 0; i < plen; i++) {
            if (!tb_sep_mbox_read(&pw[i], 5000)) {
                TEST_FAIL("Failed to read payload word %u", (unsigned)i);
            }
        }

        TEST_ASSERT_EQ(pw[0] & 0xFF, 0u, "echo cmd_seq_num");
        TEST_ASSERT_EQ(pw[1] & 0xFF, (uint32_t)ROM_KM_CMD_HW_VER, "echo command_id");

        int8_t rc = (int8_t)(pw[2] & 0xFF);
        TEST_LOG("  return_code=%d", (int)rc);
        TEST_ASSERT_EQ(rc, (uint32_t)(uint8_t)ROM_KM_RC_SUCCESS, "return_code");
        TEST_ASSERT_EQ(pw[3], (uint32_t)KMCSR_VERSION_RESET, "return_arg");
        TEST_LOG("  return_arg=0x%08X", pw[3]);

        /* Read and verify payload CRC-32C */
        uint32_t crc_word;
        if (!tb_sep_mbox_read(&crc_word, 5000)) {
            TEST_FAIL("Failed to read payload CRC word");
        }

        uint32_t exp_payload_crc = rom_crc32c((const uint8_t *)pw, (uint32_t)plen * 4);
        TEST_ASSERT_EQ(crc_word, exp_payload_crc, "Payload CRC-32C");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
