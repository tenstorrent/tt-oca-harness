/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_sigint.c
 * @brief OTP_SIGINT unrecoverable fault test.
 *
 * Verifies that a corrupted dual-rail encoding on chiplet_uid causes hardware
 * to set IRQ_STATUS.otp_sigint, the KMCSR IRQ fires, and ROM firmware takes the
 * unrecoverable path with fault code ROM_KM_UFAULT_OTP_SIGINT.
 *
 * Flow (mirrors the hardware-fault unrecoverable tests):
 *   - First run: arm the unrecoverable watcher, enable IRQs via rom_boot_init(),
 *     drive a valid OTP pattern, then inject a corrupted dual-rail pattern.
 *     The fault fires; the watcher captures the fault code and cold-resets DUT.
 *   - After restart: detect the restart, read back the captured fault code, and
 *     verify it is ROM_KM_UFAULT_OTP_SIGINT.
 *
 * Run: make run_fw FW_TEST=test_otp_sigint
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_otp.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* Disable the SRAM wipe paths so they do not interfere with this test. */
int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    /* After the unrecoverable fault, the watcher cold-resets the DUT and the
     * firmware re-runs main().  Detect that restart and verify the fault code. */
    if (tb_check_unrecoverable_restart(1000)) {
        uint32_t fault_code;
        if (!tb_get_unrecoverable_fault_code(1000, &fault_code)) {
            TEST_FAIL("Failed to get unrecoverable fault code");
        }
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_OTP_SIGINT) {
            TEST_FAIL("Wrong fault code: expected OTP_SIGINT (0x%08X), got 0x%08X",
                      (unsigned)(uint32_t)(int32_t)ROM_KM_UFAULT_OTP_SIGINT, (unsigned)fault_code);
        }
        TEST_PASS();
        return 0;
    }

    printf("OTP Signal Integrity Fault Test\n");
    printf("================================\n\n");

    if (!tb_set_timeout(500000) || !tb_drbg_set_seed(0xFA12u, 5000)) {
        TEST_FAIL("TB setup failed");
    }

    /* Arm the unrecoverable watcher; it captures the fault and resets the DUT */
    if (!tb_set_unrecoverable_watch(1, 1000u)) {
        TEST_FAIL("Failed to arm unrecoverable watcher");
    }

    /* Enable KMCSR IRQ sources (incl. otp_sigint_en) and unmask CPU IRQs */
    rom_boot_init();

    /* Drive a valid pattern first so the fields start from a valid encoding */
    tb_otp_write();
    test_delay(200);

    /* Inject corrupted dual-rail on chiplet_uid → otp_sigint → unrecoverable */
    tb_otp_write_sigint();
    test_delay(5000);

    /* Should never reach here: DUT is reset by the unrecoverable watcher */
    TEST_FAIL("OTP_SIGINT fault did not trigger unrecoverable reset (timeout)");
    return 0;
}
