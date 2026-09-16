/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_status.c
 * @brief Status and version command integration test
 *
 * Boots the KM firmware and exercises all four status/version commands
 * through the full messaging pipeline (SEP mailbox → ISR → rx_buf →
 * rom_msg_rx_process → dispatch → handler → tx_buf → ISR → outbound):
 *
 *   1. CMD_HW_VER   → SUCCESS, return_arg = KMCSR VERSION register
 *   2. CMD_ROM_VER  → SUCCESS, return_arg = ROM_KM_ROM_VERSION_* packed
 *   3. CMD_SRAM_VER → FAILURE  (no SRAM firmware loaded)
 *   4. CMD_STAT     → SUCCESS, return_arg = RECOVERABLE_ERR (0 after boot)
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_status
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

static void send_header_only(uint8_t cmd_id) {
    rom_km_msg_header_t cmd;
    cmd.seq_num = cmd_seq;
    cmd.id = cmd_id;
    cmd.payload_len = 0;
    cmd.header_crc8 = rom_crc8_rohc((const uint8_t *)&cmd, 3);

    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(cmd.raw, 5000)) TEST_FAIL("sep mbox write failed");
}

static void process_and_drain(void) {
    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

/**
 * Read a RESP_CMD and extract fields.  Verifies header CRC and resp ID.
 */
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

    if (!tb_set_timeout(500000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0x5747u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

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
     * Subtest 1: CMD_HW_VER → SUCCESS, return_arg = VERSION register
     *=================================================================*/
    TEST_SUBTEST_START("CMD_HW_VER");
    {
        send_header_only(ROM_KM_CMD_HW_VER);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "HW_VER seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_HW_VER, "HW_VER cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "HW_VER return code");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "HW_VER has return_arg");

        uint32_t hw_ver = test_read32(KEY_MANAGER_KMCSR_VERSION_BASE_ADDR);
        TEST_ASSERT_EQ(arg, hw_ver, "HW_VER matches register");
        TEST_LOG("  hw_ver = 0x%08X", hw_ver);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 2: CMD_ROM_VER → SUCCESS, return_arg = packed ROM_KM_ROM_VERSION_*
     *=================================================================*/
    TEST_SUBTEST_START("CMD_ROM_VER");
    {
        send_header_only(ROM_KM_CMD_ROM_VER);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "ROM_VER seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_ROM_VER, "ROM_VER cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "ROM_VER return code");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "ROM_VER has return_arg");

        rom_km_version_ret_t expected_ver = {.major = ROM_KM_ROM_VERSION_MAJOR,
                                             .minor = ROM_KM_ROM_VERSION_MINOR,
                                             .patch = ROM_KM_ROM_VERSION_PATCH};
        TEST_ASSERT_EQ(arg, expected_ver.raw, "ROM_VER 1.0.0");
        TEST_LOG("  rom_ver = 0x%08X", arg);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 3: CMD_SRAM_VER → FAILURE (no SRAM firmware loaded)
     *=================================================================*/
    TEST_SUBTEST_START("CMD_SRAM_VER");
    {
        send_header_only(ROM_KM_CMD_SRAM_VER);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "SRAM_VER seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_SRAM_VER, "SRAM_VER cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_FAILURE, "SRAM_VER failure");
        TEST_LOG("  SRAM_VER correctly returns FAILURE (no SRAM FW)");

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 4: CMD_STAT → SUCCESS, return_arg = RECOVERABLE_ERR
     *=================================================================*/
    TEST_SUBTEST_START("CMD_STAT");
    {
        send_header_only(ROM_KM_CMD_STAT);
        process_and_drain();

        rom_km_msg_header_t rhdr;
        uint32_t seq_e, cmd_e, arg;
        int8_t rc;
        read_resp_cmd(&rhdr, &seq_e, &cmd_e, &rc, &arg);

        TEST_ASSERT_EQ(seq_e & 0xFF, (uint32_t)cmd_seq, "STAT seq echo");
        TEST_ASSERT_EQ(cmd_e & 0xFF, (uint32_t)ROM_KM_CMD_STAT, "STAT cmd echo");
        TEST_ASSERT_EQ(rc, (int8_t)ROM_KM_RC_SUCCESS, "STAT return code");
        TEST_ASSERT_EQ(rhdr.payload_len, 4u, "STAT has return_arg");

        rom_km_stat_ret_t ret = {.raw = arg};
        uint32_t recov = test_read32(KEY_MANAGER_KMCSR_RECOVERABLE_ERR_BASE_ADDR);
        TEST_ASSERT_EQ(ret.raw, recov, "STAT matches RECOVERABLE_ERR");
        TEST_ASSERT_EQ(ret.recoverable_err, 0u, "STAT recov_fault=0 after clean boot");
        TEST_LOG("  recoverable_err = %u", (unsigned)ret.recoverable_err);

        cmd_seq++;
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
