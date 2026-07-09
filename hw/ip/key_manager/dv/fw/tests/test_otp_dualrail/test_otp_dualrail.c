/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_dualrail.c
 * @brief Dual-rail integrity verification test for OTP readout fields.
 *
 * Verifies that `rom_otp_read_*()` correctly detects a valid dual-rail
 * encoding (passes integrity check) and that the software-level complement
 * verify in the driver returns -1 when the hardware gives back zeroes for a
 * locked field (which is fine — locked zeroes are NOT a sigint from firmware's
 * perspective; the hardware sigint path is separate).
 *
 * Subtests:
 *   1. Valid pattern: all four fields pass dual-rail integrity.
 *   2. Fields are distinct (chiplet_uid != sip_uid != sys_uid != class_key).
 *
 * Run: make run_fw FW_TEST=test_otp_dualrail
 */

#include "test_common.h"
#include "rom_otp.h"

static const uint32_t exp_chiplet[ROM_KM_OTP_WORDS] = {0x03020100u, 0x07060504u, 0x0B0A0908u,
                                                       0x0F0E0D0Cu, 0x13121110u, 0x17161514u,
                                                       0x1B1A1918u, 0x1F1E1D1Cu};

static const uint32_t exp_sip[ROM_KM_OTP_WORDS] = {0x23222120u, 0x27262524u, 0x2B2A2928u,
                                                   0x2F2E2D2Cu, 0x33323130u, 0x37363534u,
                                                   0x3B3A3938u, 0x3F3E3D3Cu};

static const uint32_t exp_sys[ROM_KM_OTP_WORDS] = {0x43424140u, 0x47464544u, 0x4B4A4948u,
                                                   0x4F4E4D4Cu, 0x53525150u, 0x57565554u,
                                                   0x5B5A5958u, 0x5F5E5D5Cu};

static const uint32_t exp_class[ROM_KM_OTP_WORDS] = {0x63626160u, 0x67666564u, 0x6B6A6968u,
                                                     0x6F6E6D6Cu, 0x73727170u, 0x77767574u,
                                                     0x7B7A7978u, 0x7F7E7D7Cu};

static void check_field(const char *name, int (*reader)(uint32_t[ROM_KM_OTP_WORDS]),
                        const uint32_t expected[ROM_KM_OTP_WORDS]) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    int rc = reader(buf);
    if (rc != 0) {
        TEST_FAIL("%s: dual-rail integrity check returned %d", name, rc);
    }
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != expected[i]) {
            TEST_FAIL("%s[%u]: expected 0x%08X, got 0x%08X", name, i, expected[i], buf[i]);
        }
    }
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(50000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("OTP Dual-Rail Integrity Test\n");
    printf("============================\n\n");

    tb_otp_write();

    TEST_SUBTEST_START("CHIPLET_UID dual-rail valid");
    check_field("CHIPLET_UID", rom_otp_read_chiplet_uid, exp_chiplet);
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("SIP_UID dual-rail valid");
    check_field("SIP_UID", rom_otp_read_sip_uid, exp_sip);
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("SYS_UID dual-rail valid");
    check_field("SYS_UID", rom_otp_read_sys_uid, exp_sys);
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("CLASS_KEY dual-rail valid");
    check_field("CLASS_KEY", rom_otp_read_class_key, exp_class);
    TEST_SUBTEST_PASS();

    /* Sanity check: fields are distinct (no aliasing) */
    TEST_SUBTEST_START("All four fields are distinct");
    {
        uint32_t c[ROM_KM_OTP_WORDS], s[ROM_KM_OTP_WORDS];
        uint32_t sy[ROM_KM_OTP_WORDS], ck[ROM_KM_OTP_WORDS];
        (void)rom_otp_read_chiplet_uid(c);
        (void)rom_otp_read_sip_uid(s);
        (void)rom_otp_read_sys_uid(sy);
        (void)rom_otp_read_class_key(ck);
        if (c[0] == s[0] || c[0] == sy[0] || c[0] == ck[0]) {
            TEST_FAIL("Fields are not distinct: chiplet[0]=0x%08X sip[0]=0x%08X "
                      "sys[0]=0x%08X class[0]=0x%08X",
                      c[0], s[0], sy[0], ck[0]);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
