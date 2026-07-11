/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_read_lock.c
 * @brief OTP_READ_LOCK register functional test.
 *
 * Subtests:
 *   1. Before locking: all fields return valid non-zero data.
 *   2. Lock chiplet_uid: subsequent reads return all-zero (hardware masks).
 *   3. Lock class_key:   subsequent reads return all-zero.
 *   4. Other fields (sip_uid, sys_uid) remain readable after the above locks.
 *   5. Write-1-only: writing 0 to OTP_READ_LOCK does not clear set bits.
 *   6. OTP_CHANGE_STATUS can be read and W1C-cleared.
 *
 * Run: make run_fw FW_TEST=test_otp_read_lock
 */

#include "test_common.h"
#include "rom_otp.h"

int main(void) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    int rc;

    TEST_INIT();

    if (!tb_set_timeout(100000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("OTP Read-Lock Test\n");
    printf("==================\n\n");

    tb_otp_write();

    /* 1. Pre-lock: all fields return valid data */
    TEST_SUBTEST_START("Pre-lock: chiplet_uid readable");
    rc = rom_otp_read_chiplet_uid(buf);
    if (rc != 0) TEST_FAIL("chiplet_uid: pre-lock dual-rail check failed");
    if (buf[0] == 0 && buf[1] == 0) TEST_FAIL("chiplet_uid: pre-lock returns zero");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Pre-lock: class_key readable");
    rc = rom_otp_read_class_key(buf);
    if (rc != 0) TEST_FAIL("class_key: pre-lock dual-rail check failed");
    if (buf[0] == 0 && buf[1] == 0) TEST_FAIL("class_key: pre-lock returns zero");
    TEST_SUBTEST_PASS();

    /* 2. Lock chiplet_uid */
    TEST_SUBTEST_START("Lock chiplet_uid");
    rom_otp_set_read_lock(KM_CSR__OTP_READ_LOCK_REG__CHIPLET_UID_bm);

    /*
     * After lock: hardware returns zero for all value and complement words.
     * The software driver sees value=0 and cpl=0 → value != ~cpl (for 32-bit
     * words: 0 != 0xFFFFFFFF), so the driver returns -1 (sigint failure).
     * That is expected for a locked field — the caller should not read a
     * locked field and expect valid data.
     */
    rc = rom_otp_read_chiplet_uid(buf);
    /* Return code -1 is expected: all-zero from HW fails complement check */
    if (buf[0] != 0 || buf[1] != 0 || buf[2] != 0 || buf[3] != 0 || buf[4] != 0 || buf[5] != 0 ||
        buf[6] != 0 || buf[7] != 0) {
        TEST_FAIL("chiplet_uid: post-lock reads non-zero (hw masking not working)");
    }
    TEST_SUBTEST_PASS();

    /* 3. Lock class_key */
    TEST_SUBTEST_START("Lock class_key");
    rom_otp_set_read_lock(KM_CSR__OTP_READ_LOCK_REG__CLASS_KEY_bm);
    rc = rom_otp_read_class_key(buf);
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != 0) {
            TEST_FAIL("class_key[%u]: post-lock returns non-zero 0x%08X", i, buf[i]);
        }
    }
    TEST_SUBTEST_PASS();

    /* 4. sip_uid and sys_uid are still unlocked and readable */
    TEST_SUBTEST_START("sip_uid and sys_uid remain readable after chiplet/class locks");
    rc = rom_otp_read_sip_uid(buf);
    if (rc != 0) TEST_FAIL("sip_uid: dual-rail check failed after unrelated lock");
    if (buf[0] == 0 && buf[1] == 0) TEST_FAIL("sip_uid: unexpectedly zero after unrelated lock");

    rc = rom_otp_read_sys_uid(buf);
    if (rc != 0) TEST_FAIL("sys_uid: dual-rail check failed after unrelated lock");
    if (buf[0] == 0 && buf[1] == 0) TEST_FAIL("sys_uid: unexpectedly zero after unrelated lock");
    TEST_SUBTEST_PASS();

    /* 5. Write-1-only: writing 0 to OTP_READ_LOCK does not clear locked bits */
    TEST_SUBTEST_START("Write-1-only: 0-write cannot clear locked bits");
    {
        /* Directly write 0 to the register */
        km_csr__otp_read_lock_reg_t clr = {0};
        ROM_OTP_READ_LOCK_REG = clr;
        /* chiplet_uid should still be locked */
        rc = rom_otp_read_chiplet_uid(buf);
        for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
            if (buf[i] != 0) {
                TEST_FAIL("chiplet_uid[%u]: not zero after 0-write to READ_LOCK (lock cleared!)",
                          i);
            }
        }
    }
    TEST_SUBTEST_PASS();

    /* 6. OTP_CHANGE_STATUS: read and W1C-clear */
    TEST_SUBTEST_START("OTP_CHANGE_STATUS read and W1C clear");
    {
        uint32_t cs = rom_otp_get_change_status();
        /* Clear whatever bits are set */
        rom_otp_clear_change_status(cs);
        uint32_t cs2 = rom_otp_get_change_status();
        if (cs2 != 0) {
            TEST_FAIL("OTP_CHANGE_STATUS: not zero after W1C clear (got 0x%08X)", cs2);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
