/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_recov_fault.c
 * @brief Recoverable fault register verification test
 *
 * Verifies that triggering a recoverable fault correctly sets the
 * KMCSR RECOVERABLE_ERR register and produces a RESP_RECOVERABLE_FAULT
 * response:
 *   1. Verify RECOVERABLE_ERR is initially 0 after boot
 *   2. Trigger ROM_KM_RFAULT_KEY_SLOT_CRC via rom_trigger_recoverable()
 *   3. Verify RECOVERABLE_ERR is now set
 *   4. Drain the fault response
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_recov_fault
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_isr.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000)) TEST_FAIL("Failed to set testbench timeout");

    if (!tb_drbg_set_seed(0xF061u, 5000)) TEST_FAIL("tb_drbg_set_seed failed");

    rom_boot_init();

    uint32_t ready;
    tb_sep_mbox_read(&ready, 5000);

    /*=================================================================
     * Subtest 1: RECOVERABLE_ERR initially 0
     *=================================================================*/
    TEST_SUBTEST_START("RECOVERABLE_ERR initially 0");
    {
        uint32_t recov = test_read32(KEY_MANAGER_KMCSR_RECOVERABLE_ERR_BASE_ADDR);
        TEST_ASSERT_EQ(recov & 1, 0, "recov_err initially 0");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 2: Trigger fault and verify register set
     *=================================================================*/
    TEST_SUBTEST_START("Trigger fault sets RECOVERABLE_ERR");
    {
        rom_trigger_recoverable(ROM_KM_RFAULT_KEY_SLOT_CRC);

        uint32_t recov = test_read32(KEY_MANAGER_KMCSR_RECOVERABLE_ERR_BASE_ADDR);
        TEST_ASSERT_EQ(recov & 1, 1, "recov_err set after fault");
    }
    TEST_SUBTEST_PASS();

    /*=================================================================
     * Subtest 3: Drain fault response
     *=================================================================*/
    TEST_SUBTEST_START("RESP_RECOVERABLE_FAULT received");
    {
        test_delay(500);

        uint32_t fault_hdr;
        if (!tb_sep_mbox_read(&fault_hdr, 5000)) TEST_FAIL("No RESP_RECOVERABLE_FAULT in outbound");

        rom_km_msg_header_t fh;
        fh.raw = fault_hdr;
        TEST_ASSERT_EQ(fh.id, ROM_KM_RESP_RECOVERABLE_FAULT, "got fault response");

        /* Drain payload + CRC */
        if (fh.payload_len > 0) {
            uint32_t fpl;
            tb_sep_mbox_read(&fpl, 5000);
            uint32_t fcrc;
            tb_sep_mbox_read(&fcrc, 5000);
        }
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
