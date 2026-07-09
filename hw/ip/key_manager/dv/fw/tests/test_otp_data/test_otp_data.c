/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_data.c
 * @brief OTP data register read-through test
 *
 * After testbench drives otp_data_i (via TB_CMD_OTP_WRITE), firmware reads all
 * KMCSR OTP readout registers and verifies the values match the known pattern
 * driven by the testbench:
 *
 *   life_cycle     = 0xA5  (dual-rail; decodes to lc=0x5)
 *   demotion_state = 0b01/0b10 (dual-rail; decodes to demote_1=1, demote_2=0)
 *   chiplet_uid    = bytes 0x00..0x1F (dual-rail, 256-bit value)
 *   sip_uid        = bytes 0x20..0x3F (dual-rail, 256-bit value)
 *   sys_uid        = bytes 0x40..0x5F (dual-rail, 256-bit value)
 *   class_key      = bytes 0x60..0x7F (dual-rail, 256-bit value)
 *
 * Uses rom_otp.h driver functions which verify dual-rail integrity.
 *
 * Run: make run_fw FW_TEST=test_otp_data
 */

#include "test_common.h"
#include "rom_otp.h"

/* Expected DECODED values (must match testbench _handle_otp_write pattern) */
#define EXP_LIFE_CYCLE 0x5u
#define EXP_DEMOTE_1 1u
#define EXP_DEMOTE_2 0u

/*
 * Expected 256-bit values as 8 x uint32_t (word 0 = bits [31:0]).
 * Pattern: bytes N*32..(N*32)+31, word i = bytes [4i+3..4i].
 */
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

int main(void) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    int rc;

    TEST_INIT();

    if (!tb_set_timeout(50000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("OTP Data Read-Through Test\n");
    printf("==========================\n\n");

    /* Ask testbench to drive OTP port with known pattern */
    tb_otp_write();

    /* --- Life-cycle (dual-rail decode + verify) --- */
    TEST_SUBTEST_START("OTP_LIFE_CYCLE decoded value");
    {
        uint8_t lc;
        if (rom_otp_read_life_cycle(&lc) != 0) {
            TEST_FAIL("OTP_LIFE_CYCLE: dual-rail integrity check failed");
        }
        if (lc != EXP_LIFE_CYCLE) {
            TEST_FAIL("OTP_LIFE_CYCLE: expected 0x%02X, got 0x%02X", EXP_LIFE_CYCLE, (unsigned)lc);
        }
    }
    TEST_SUBTEST_PASS();

    /* --- Demotion state (dual-rail decode + verify) --- */
    TEST_SUBTEST_START("OTP_DEMOTION_STATE decoded value");
    {
        uint8_t dem;
        if (rom_otp_read_demotion(&dem) != 0) {
            TEST_FAIL("OTP_DEMOTION_STATE: dual-rail integrity check failed");
        }
        uint8_t dem1 = dem & 0x1u;
        uint8_t dem2 = (dem >> 1) & 0x1u;
        if (dem1 != EXP_DEMOTE_1) {
            TEST_FAIL("OTP_DEMOTION_STATE demote_1: expected %u, got %u", EXP_DEMOTE_1,
                      (unsigned)dem1);
        }
        if (dem2 != EXP_DEMOTE_2) {
            TEST_FAIL("OTP_DEMOTION_STATE demote_2: expected %u, got %u", EXP_DEMOTE_2,
                      (unsigned)dem2);
        }
    }
    TEST_SUBTEST_PASS();

    /* --- CHIPLET_UID dual-rail readout --- */
    TEST_SUBTEST_START("OTP_CHIPLET_UID dual-rail readout");
    rc = rom_otp_read_chiplet_uid(buf);
    if (rc != 0) {
        TEST_FAIL("CHIPLET_UID: dual-rail integrity check failed");
    }
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != exp_chiplet[i]) {
            TEST_FAIL("CHIPLET_UID[%u]: expected 0x%08X, got 0x%08X", i, exp_chiplet[i], buf[i]);
        }
    }
    TEST_SUBTEST_PASS();

    /* --- SIP_UID dual-rail readout --- */
    TEST_SUBTEST_START("OTP_SIP_UID dual-rail readout");
    rc = rom_otp_read_sip_uid(buf);
    if (rc != 0) {
        TEST_FAIL("SIP_UID: dual-rail integrity check failed");
    }
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != exp_sip[i]) {
            TEST_FAIL("SIP_UID[%u]: expected 0x%08X, got 0x%08X", i, exp_sip[i], buf[i]);
        }
    }
    TEST_SUBTEST_PASS();

    /* --- SYS_UID dual-rail readout --- */
    TEST_SUBTEST_START("OTP_SYS_UID dual-rail readout");
    rc = rom_otp_read_sys_uid(buf);
    if (rc != 0) {
        TEST_FAIL("SYS_UID: dual-rail integrity check failed");
    }
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != exp_sys[i]) {
            TEST_FAIL("SYS_UID[%u]: expected 0x%08X, got 0x%08X", i, exp_sys[i], buf[i]);
        }
    }
    TEST_SUBTEST_PASS();

    /* --- CLASS_KEY dual-rail readout --- */
    TEST_SUBTEST_START("OTP_CLASS_KEY dual-rail readout");
    rc = rom_otp_read_class_key(buf);
    if (rc != 0) {
        TEST_FAIL("CLASS_KEY: dual-rail integrity check failed");
    }
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != exp_class[i]) {
            TEST_FAIL("CLASS_KEY[%u]: expected 0x%08X, got 0x%08X", i, exp_class[i], buf[i]);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
