/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_recov_mbox.c
 * @brief T060 - Mailbox fault recovery test
 *
 * Tests the recoverable fault mechanism by directly triggering a fault
 * and verifying the recovery acknowledgment path:
 *   1. Send CMD_HW_VER to establish seq=0
 *   2. Trigger ROM_KM_RFAULT_MBOX_OVERFLOW via rom_trigger_recoverable()
 *   3. Verify RESP_RECOVERABLE_FAULT is received
 *   4. Send CMD_RECOV_ACK and verify SUCCESS
 *   5. Trigger SEP-side FLUSH and verify the recovery ISR restores
 *      inbound mailbox IRQ enable before returning
 *
 * Actual mailbox overflow/underflow injection requires cocotb stimulus.
 * This test exercises the firmware-side fault trigger and acknowledgment
 * logic, and uses the testbench mailbox helpers to inject a SEP flush.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_recov_mbox
 */

#include "test_common.h"
#include "irq_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_mailbox.h"
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

static void drain_fault_response_expect(int8_t expected_fault_code) {
    uint32_t fault_hdr;
    if (!tb_sep_mbox_read(&fault_hdr, 5000u)) TEST_FAIL("No RESP_RECOVERABLE_FAULT in outbound");

    rom_km_msg_header_t fh;
    fh.raw = fault_hdr;
    TEST_ASSERT_EQ(fh.id, ROM_KM_RESP_RECOVERABLE_FAULT, "got recov fault resp");
    TEST_ASSERT_EQ(fh.payload_len, 1u, "recoverable fault payload length");

    uint32_t fault_payload = 0u;
    uint32_t fault_crc = 0u;
    uint32_t expected_crc;

    if (!tb_sep_mbox_read(&fault_payload, 5000u))
        TEST_FAIL("Failed to read recoverable fault payload");
    if (!tb_sep_mbox_read(&fault_crc, 5000u)) TEST_FAIL("Failed to read recoverable fault CRC");

    expected_crc = rom_crc32c((const uint8_t *)&fault_payload, sizeof(fault_payload));
    TEST_ASSERT_EQ(fault_payload, (uint32_t)(int32_t)expected_fault_code,
                   "recoverable fault payload");
    TEST_ASSERT_EQ(fault_crc, expected_crc, "recoverable fault CRC");
}

static uint32_t inbound_irq_enabled(void) {
    km_mailbox_km__irq_enable_reg_t irq_en = {.w = rom_mailbox_irq_enable_read()};
    return (uint32_t)irq_en.f.inbound_read_data_avail_en;
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xF060u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    uint32_t ready;
    tb_sep_mbox_read(&ready, 5000);

    /*=================================================================
     * Subtest 1: Establish baseline with CMD_HW_VER
     *=================================================================*/
    TEST_SUBTEST_START("CMD_HW_VER baseline");
    {
        send_header_only(ROM_KM_CMD_HW_VER);
        process_and_drain();

        uint32_t rp[8];
        read_resp_cmd(rp, 8);
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 2: Trigger recoverable fault and verify response
     *=================================================================*/
    TEST_SUBTEST_START("Trigger recoverable fault");
    {
        rom_trigger_recoverable(ROM_KM_RFAULT_MBOX_OVERFLOW);
        test_delay(500);

        uint32_t fault_hdr;
        if (!tb_sep_mbox_read(&fault_hdr, 5000)) TEST_FAIL("No RESP_RECOVERABLE_FAULT in outbound");

        rom_km_msg_header_t fh;
        fh.raw = fault_hdr;
        TEST_ASSERT_EQ(fh.id, ROM_KM_RESP_RECOVERABLE_FAULT, "got recov fault resp");

        /* Drain payload + CRC */
        if (fh.payload_len > 0) {
            uint32_t fpl;
            tb_sep_mbox_read(&fpl, 5000);
            uint32_t fcrc;
            tb_sep_mbox_read(&fcrc, 5000);
        }
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 3: CMD_RECOV_ACK clears the fault
     *=================================================================*/
    TEST_SUBTEST_START("CMD_RECOV_ACK success");
    {
        send_header_only(ROM_KM_CMD_RECOV_ACK);
        process_and_drain();

        uint32_t rp[8];
        int8_t rc = read_resp_cmd(rp, 8);
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "recov_ack success");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 4: flushed_by_sep recovery must restore inbound IRQ enable
     *=================================================================*/
    TEST_SUBTEST_START("SEP flush recovery re-enables inbound IRQ");
    {
        rom_mailbox_disable_inbound_irq();
        TEST_ASSERT_EQ(inbound_irq_enabled(), 0u, "precondition: inbound IRQ disabled");

        if (!tb_sep_mbox_ctrl_write(1u << 2, 5000u))
            TEST_FAIL("Failed to trigger SEP mailbox flush");
        test_delay(100u);

        rom_isr_mailbox();

        drain_fault_response_expect(ROM_KM_RFAULT_FLUSHED_BY_SEP);
        TEST_ASSERT_EQ(inbound_irq_enabled(), 1u, "flush recovery must re-enable inbound IRQ");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
