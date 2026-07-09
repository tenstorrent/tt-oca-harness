/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_recov_ack.c
 * @brief T062 - Fault acknowledgment full flow test
 *
 * Exercises the complete recoverable fault lifecycle:
 *   1. Boot, generate a key to establish normal operation
 *   2. Trigger a recoverable fault
 *   3. Verify CMD_KEY_GENERATE is restricted (FAILURE)
 *   4. Verify CMD_STAT reports recov_fault bit set
 *   5. Send CMD_RECOV_ACK and verify SUCCESS
 *   6. Verify CMD_KEY_GENERATE succeeds again (normal operation)
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_recov_ack
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

/**
 * Drain a RESP_RECOVERABLE_FAULT from the outbound mailbox.
 * The fault response is sent directly (header + 1 payload word + CRC).
 */
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

    if (!tb_drbg_set_seed(0xF062u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    uint32_t ready;
    tb_sep_mbox_read(&ready, 5000);

    /*=================================================================
     * Step 1: Generate a key to establish normal operation
     *=================================================================*/
    TEST_SUBTEST_START("Baseline CMD_KEY_GENERATE 256-bit AES");
    {
        uint32_t payload[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen baseline success");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 2: Trigger recoverable fault
     *=================================================================*/
    TEST_SUBTEST_START("Trigger recoverable fault");
    {
        rom_trigger_recoverable(ROM_KM_RFAULT_KEY_SLOT_CRC);
        drain_fault_response();
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 3: CMD_KEY_GENERATE restricted during fault
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_GENERATE restricted");
    {
        uint32_t payload[2] = {7u, (rom_km_dest_bits_t){.aes = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "keygen restricted");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 4: CMD_STAT reports recov_fault bit set
     *=================================================================*/
    TEST_SUBTEST_START("CMD_STAT shows recov_fault=1");
    {
        send_header_only(ROM_KM_CMD_STAT);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "STAT success");
        rom_km_stat_ret_t stat_ret = {.raw = rp[3]};
        TEST_ASSERT_EQ(stat_ret.recoverable_err, 1u, "recov_fault bit set");
        TEST_LOG("  STAT return_arg = 0x%08X", stat_ret.raw);
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Step 5: CMD_RECOV_ACK clears fault
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

    /*=================================================================
     * Step 6: CMD_KEY_GENERATE succeeds again
     *=================================================================*/
    TEST_SUBTEST_START("CMD_KEY_GENERATE restored");
    {
        uint32_t payload[2] = {3u, (rom_km_dest_bits_t){.hmac_sha2 = 1}.raw};
        send_cmd_with_payload(ROM_KM_CMD_KEY_GENERATE, payload, 2);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "keygen restored success");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
