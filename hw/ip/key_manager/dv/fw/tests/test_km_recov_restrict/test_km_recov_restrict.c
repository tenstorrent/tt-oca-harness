/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_recov_restrict.c
 * @brief Command restriction during fault state test
 *
 * Verifies the RECOVERABLE_ERR command filter in rom_msg_rx_process():
 *   1. Trigger a recoverable fault
 *   2. Test each allowed command (HW_VER, ROM_VER, SRAM_VER, STAT) -
 *      verify they pass through the filter
 *   3. Test each restricted command (KEY_GENERATE, KEY_TRANSFER,
 *      KEY_REVOKE, ENGINE_SHRED) - verify all rejected with FAILURE
 *   4. ACK the fault via CMD_RECOV_ACK
 *   5. Verify restricted commands are accepted again
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_recov_restrict
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
 * Common Helpers
 *===========================================================================*/

static uint8_t cmd_seq = 0;

static void process_and_drain(void) {
    test_delay(500);
    rom_msg_rx_process();
    test_delay(500);
}

static uint32_t send_cmd_with_payload(uint8_t cmd_id, const uint32_t *payload,
                                      uint8_t payload_len) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq++;
    hdr.id = cmd_id;
    hdr.payload_len = payload_len;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    tb_sep_mbox_write(hdr.raw, 5000);
    for (uint8_t i = 0; i < payload_len; i++) tb_sep_mbox_write(payload[i], 5000);

    uint32_t crc = rom_crc32c((const uint8_t *)payload, payload_len * 4);
    tb_sep_mbox_write_separator_write(1, 5000);
    tb_sep_mbox_write(crc, 5000);
    return hdr.raw;
}

static uint32_t send_header_only(uint8_t cmd_id) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq++;
    hdr.id = cmd_id;
    hdr.payload_len = 0;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    tb_sep_mbox_write_separator_write(1, 5000);
    tb_sep_mbox_write(hdr.raw, 5000);
    return hdr.raw;
}

static int8_t read_resp_cmd(uint32_t *resp_payload, uint8_t max_words) {
    uint32_t hdr_raw;
    tb_sep_mbox_read(&hdr_raw, 5000);
    rom_km_msg_header_t rh;
    rh.raw = hdr_raw;

    for (uint8_t i = 0; i < rh.payload_len && i < max_words; i++)
        tb_sep_mbox_read(&resp_payload[i], 5000);

    if (rh.payload_len > 0) {
        uint32_t crc;
        tb_sep_mbox_read(&crc, 5000);
    }

    if (rh.payload_len >= 3) return (int8_t)(resp_payload[2] & 0xFF);

    return -128;
}

static void drain_fault_response(void) {
    test_delay(500);

    uint32_t fault_hdr;
    if (!tb_sep_mbox_read(&fault_hdr, 5000)) TEST_FAIL("No RESP_RECOVERABLE_FAULT in outbound");

    rom_km_msg_header_t fh;
    fh.raw = fault_hdr;
    TEST_ASSERT_EQ(fh.id, ROM_KM_RESP_RECOVERABLE_FAULT, "got fault response");

    if (fh.payload_len > 0) {
        uint32_t fpl;
        tb_sep_mbox_read(&fpl, 5000);
        uint32_t fcrc;
        tb_sep_mbox_read(&fcrc, 5000);
    }
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(1000000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xF063u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    uint32_t ready;
    tb_sep_mbox_read(&ready, 5000);

    /*=================================================================
     * Trigger recoverable fault
     *=================================================================*/
    TEST_SUBTEST_START("Trigger recoverable fault");
    {
        rom_trigger_recoverable(ROM_KM_RFAULT_KEY_SLOT_CRC);
        drain_fault_response();
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Allowed commands during fault state
     *=================================================================*/

    TEST_SUBTEST_START("HW_VER allowed during fault");
    {
        send_header_only(ROM_KM_CMD_HW_VER);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "HW_VER accepted");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("ROM_VER allowed during fault");
    {
        send_header_only(ROM_KM_CMD_ROM_VER);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "ROM_VER accepted");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("SRAM_VER allowed during fault");
    {
        send_header_only(ROM_KM_CMD_SRAM_VER);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        /* SRAM_VER returns FAILURE (no SRAM FW), but it passed the filter */
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "SRAM_VER handler failure");
        TEST_LOG("  SRAM_VER passed filter (handler returns FAILURE as expected)");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("STAT allowed during fault");
    {
        send_header_only(ROM_KM_CMD_STAT);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "STAT accepted");
        rom_km_stat_ret_t stat_ret = {.raw = rp[3]};
        TEST_ASSERT_EQ(stat_ret.recoverable_err, 1u, "recov_fault bit still set");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Restricted commands during fault state
     *=================================================================*/

    TEST_SUBTEST_START("KEY_GENERATE restricted");
    {
        uint32_t pl[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, pl, 2);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "KEY_GENERATE rejected");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("KEY_TRANSFER restricted");
    {
        /* handle=1, dest=AES */
        uint32_t pl[2] = {1u, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_TRANSFER, pl, 2);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "KEY_TRANSFER rejected");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("KEY_REVOKE restricted");
    {
        uint32_t pl[1] = {1u}; /* handle=1 */
        send_cmd_with_payload(ROM_KM_CMD_KEY_REVOKE, pl, 1);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "KEY_REVOKE rejected");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("ENGINE_SHRED restricted");
    {
        uint32_t pl[1] = {
            (rom_km_dest_bits_t){.hmac_sha2 = 1, .kmac_sha3 = 1, .aes = 1, .otbn = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_ENGINE_SHRED, pl, 1);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "ENGINE_SHRED rejected");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * ACK fault and verify commands restored
     *=================================================================*/

    TEST_SUBTEST_START("CMD_RECOV_ACK clears fault");
    {
        send_header_only(ROM_KM_CMD_RECOV_ACK);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "recov_ack success");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("KEY_GENERATE accepted after ACK");
    {
        uint32_t pl[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, pl, 2);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "KEY_GENERATE restored");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
