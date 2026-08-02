/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_cmd_otp_read_lock_cold.c
 * @brief CMD_OTP_READ_LOCK_COLD (0x28) functional test.
 *
 * Subtests:
 *   1. Happy path: send CMD_OTP_READ_LOCK_COLD with chiplet_uid bit only;
 *      verify RESP_CMD SUCCESS, return_arg has chiplet_uid bit set, and
 *      OTP_READ_LOCK_COLD register reflects the new bit.
 *   2. OR-gate: chiplet_uid reads all-zero (cold lock effective) while the
 *      warm OTP_READ_LOCK register is still 0.
 *   3. Unlocked field (sip_uid) remains readable after unrelated cold lock.
 *   4. Multi-field: set sip_uid and sys_uid cold locks together; both now
 *      return zero, chiplet_uid still zero from step 1.
 *   5. Write-1-only: writing 0 does not clear cold-locked bits.
 *   6. Error — invalid payload length (0 words): INVALID_LEN.
 *   7. Error — reserved bits set in lock_bits: INVALID_ARG.
 *
 * Run: make run_fw FW_TEST=test_km_cmd_otp_read_lock_cold
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_crc.h"
#include "rom_isr.h"
#include "rom_boot.h"
#include "rom_otp.h"
#include "key_manager_fw.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/*===========================================================================
 * Helpers (same pattern as test_km_cmd_key_load.c)
 *===========================================================================*/

static uint8_t cmd_seq;

static void send_cmd_no_payload(uint8_t cmd_id) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = 0;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    /* Zero-payload frame: separator first, then header (no payload, no CRC). */
    if (!tb_sep_mbox_write_separator_write(1, 5000))
        TEST_FAIL("separator write failed (no-payload)");
    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed (no-payload)");
}

static void send_cmd_one_word(uint8_t cmd_id, uint32_t word0) {
    rom_km_msg_header_t hdr;
    hdr.seq_num = cmd_seq;
    hdr.id = cmd_id;
    hdr.payload_len = 1;
    hdr.header_crc8 = rom_crc8_rohc((const uint8_t *)&hdr, 3);

    if (!tb_sep_mbox_write(hdr.raw, 5000)) TEST_FAIL("header write failed");
    if (!tb_sep_mbox_write(word0, 5000)) TEST_FAIL("payload word0 write failed");

    uint32_t crc = rom_crc32c((const uint8_t *)&word0, 4u);
    if (!tb_sep_mbox_write_separator_write(1, 5000)) TEST_FAIL("separator write failed");
    if (!tb_sep_mbox_write(crc, 5000)) TEST_FAIL("CRC write failed");
}

static void process_and_drain(void) {
    test_delay(1000);
    rom_msg_rx_process();
    rom_isr_mailbox();
}

static void read_resp_cmd(int8_t *rc_out, uint32_t *arg_out) {
    rom_km_msg_header_t rhdr;
    uint32_t payload_words[4] = {0};
    uint32_t word;

    if (!tb_sep_mbox_read(&word, 5000)) TEST_FAIL("Failed to read response header");
    rhdr.raw = word;

    uint8_t exp_crc = rom_crc8_rohc((const uint8_t *)&word, 3);
    TEST_ASSERT_EQ((uint32_t)rhdr.header_crc8, (uint32_t)exp_crc, "resp header CRC");
    TEST_ASSERT_EQ((uint32_t)rhdr.id, (uint32_t)ROM_KM_RESP_CMD, "resp ID");

    uint32_t seq_echo, cmd_echo, rc_word;
    if (!tb_sep_mbox_read(&seq_echo, 5000)) TEST_FAIL("seq echo read failed");
    payload_words[0] = seq_echo;
    if (!tb_sep_mbox_read(&cmd_echo, 5000)) TEST_FAIL("cmd echo read failed");
    payload_words[1] = cmd_echo;
    if (!tb_sep_mbox_read(&rc_word, 5000)) TEST_FAIL("rc word read failed");
    payload_words[2] = rc_word;
    *rc_out = (int8_t)(rc_word & 0xFFu);

    if (rhdr.payload_len >= 4u) {
        if (!tb_sep_mbox_read(arg_out, 5000)) TEST_FAIL("return arg read failed");
        payload_words[3] = *arg_out;
    } else {
        *arg_out = 0;
    }

    uint32_t crc_word;
    if (!tb_sep_mbox_read(&crc_word, 5000)) TEST_FAIL("payload CRC read failed");
    TEST_ASSERT(rhdr.payload_len == 3u || rhdr.payload_len == 4u, "resp payload_len=%u",
                (unsigned)rhdr.payload_len);
    TEST_ASSERT_EQ(crc_word,
                   rom_crc32c((const uint8_t *)payload_words, (uint32_t)rhdr.payload_len * 4u),
                   "resp payload CRC");
}

/*===========================================================================
 * Test body
 *===========================================================================*/

int main(void) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    int8_t rc;
    uint32_t arg;

    TEST_INIT();

    if (!tb_set_timeout(1000000)) TEST_FAIL("Failed to set testbench timeout");

    rom_boot_init();

    /* Discard RESP_KM_READY emitted by rom_boot_init() */
    {
        uint32_t ready;
        if (!tb_sep_mbox_read(&ready, 5000)) TEST_FAIL("No RESP_KM_READY after boot");
        rom_km_msg_header_t rdy;
        rdy.raw = ready;
        TEST_ASSERT_EQ((uint32_t)rdy.id, (uint32_t)ROM_KM_RESP_KM_READY, "boot response id");
    }
    cmd_seq = 0;

    printf("CMD_OTP_READ_LOCK_COLD Test\n");
    printf("===========================\n\n");

    /* Prime the testbench OTP data and wait for it to propagate */
    tb_otp_write();
    test_delay(200);

    /*-----------------------------------------------------------------------
     * Subtest 1: Happy path — lock chiplet_uid only via command
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("Happy path: CMD_OTP_READ_LOCK_COLD locks chiplet_uid");

    /* Warm lock register must be 0 before we send the command */
    TEST_ASSERT_EQ(ROM_OTP_READ_LOCK_REG.w, 0u,
                   "OTP_READ_LOCK should be 0 before cold-lock command");

    send_cmd_one_word(ROM_KM_CMD_OTP_READ_LOCK_COLD,
                      KM_CSR__OTP_READ_LOCK_COLD_REG__CHIPLET_UID_bm);
    cmd_seq++;
    process_and_drain();
    read_resp_cmd(&rc, &arg);

    TEST_ASSERT_EQ((int32_t)rc, (int32_t)ROM_KM_RC_SUCCESS, "CMD_OTP_READ_LOCK_COLD rc");
    TEST_ASSERT(arg & KM_CSR__OTP_READ_LOCK_COLD_REG__CHIPLET_UID_bm,
                "return_arg chiplet_uid bit set (arg=0x%08X)", (unsigned)arg);

    /* OTP_READ_LOCK_COLD register must reflect the bit */
    TEST_ASSERT(ROM_OTP_READ_LOCK_COLD_REG.w & KM_CSR__OTP_READ_LOCK_COLD_REG__CHIPLET_UID_bm,
                "OTP_READ_LOCK_COLD.chiplet_uid not set after command");

    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 2: OR-gate — chiplet_uid reads all-zero, warm lock still 0
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("OR-gate: cold lock gates chiplet_uid; warm lock stays 0");

    TEST_ASSERT_EQ(ROM_OTP_READ_LOCK_REG.w, 0u,
                   "OTP_READ_LOCK (warm) must stay 0 — only cold lock set");

    (void)rom_otp_read_chiplet_uid(buf);
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != 0u) {
            TEST_FAIL("chiplet_uid[%u]: 0x%08X (expected 0 — cold-locked)", i, (unsigned)buf[i]);
        }
    }

    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 3: Unlocked field — sip_uid still readable
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("Unlocked field: sip_uid readable after chiplet cold-lock");

    if (rom_otp_read_sip_uid(buf) != 0)
        TEST_FAIL("sip_uid: dual-rail integrity failed (should be readable)");
    if (buf[0] == 0u && buf[7] == 0u)
        TEST_FAIL("sip_uid: unexpectedly zero after unrelated cold-lock");

    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 4: Multi-field — set sip_uid and sys_uid together
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("Multi-field: lock sip_uid and sys_uid together");

    send_cmd_one_word(ROM_KM_CMD_OTP_READ_LOCK_COLD,
                      KM_CSR__OTP_READ_LOCK_COLD_REG__SIP_UID_bm |
                          KM_CSR__OTP_READ_LOCK_COLD_REG__SYS_UID_bm);
    cmd_seq++;
    process_and_drain();
    read_resp_cmd(&rc, &arg);

    TEST_ASSERT_EQ((int32_t)rc, (int32_t)ROM_KM_RC_SUCCESS,
                   "multi-field CMD_OTP_READ_LOCK_COLD rc");
    TEST_ASSERT(arg & KM_CSR__OTP_READ_LOCK_COLD_REG__SIP_UID_bm,
                "return_arg sip_uid bit set (arg=0x%08X)", (unsigned)arg);
    TEST_ASSERT(arg & KM_CSR__OTP_READ_LOCK_COLD_REG__SYS_UID_bm,
                "return_arg sys_uid bit set (arg=0x%08X)", (unsigned)arg);
    TEST_ASSERT(arg & KM_CSR__OTP_READ_LOCK_COLD_REG__CHIPLET_UID_bm,
                "return_arg chiplet_uid bit still set (arg=0x%08X)", (unsigned)arg);

    /* sip_uid and sys_uid now read zero */
    (void)rom_otp_read_sip_uid(buf);
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != 0u)
            TEST_FAIL("sip_uid[%u]: non-zero after cold-lock (0x%08X)", i, (unsigned)buf[i]);
    }
    (void)rom_otp_read_sys_uid(buf);
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != 0u)
            TEST_FAIL("sys_uid[%u]: non-zero after cold-lock (0x%08X)", i, (unsigned)buf[i]);
    }

    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 5: Write-1-only — writing 0 does not clear cold-locked bits
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("Write-1-only: 0-write cannot clear cold-locked bits");

    {
        km_csr__otp_read_lock_cold_reg_t clr = {0};
        ROM_OTP_READ_LOCK_COLD_REG = clr;
        TEST_ASSERT(ROM_OTP_READ_LOCK_COLD_REG.w & KM_CSR__OTP_READ_LOCK_COLD_REG__CHIPLET_UID_bm,
                    "chiplet_uid cold-lock cleared by 0-write (should not happen)");
        (void)rom_otp_read_chiplet_uid(buf);
        for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
            if (buf[i] != 0u)
                TEST_FAIL("chiplet_uid[%u]: non-zero after 0-write (cold-lock cleared!)", i);
        }
    }

    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 6: Error — no payload words → INVALID_LEN
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("Error: zero-payload CMD_OTP_READ_LOCK_COLD → INVALID_LEN");

    send_cmd_no_payload(ROM_KM_CMD_OTP_READ_LOCK_COLD);
    cmd_seq++;
    process_and_drain();
    read_resp_cmd(&rc, &arg);

    TEST_ASSERT_EQ((int32_t)rc, (int32_t)ROM_KM_RC_INVALID_LEN, "empty payload rc");

    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 7: Error — reserved bits set → INVALID_ARG
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("Error: reserved bits set in lock_bits → INVALID_ARG");

    send_cmd_one_word(ROM_KM_CMD_OTP_READ_LOCK_COLD, 0x80u); /* bit 7 = reserved */
    cmd_seq++;
    process_and_drain();
    read_resp_cmd(&rc, &arg);

    TEST_ASSERT_EQ((int32_t)rc, (int32_t)ROM_KM_RC_INVALID_ARG, "reserved bits rc");

    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
