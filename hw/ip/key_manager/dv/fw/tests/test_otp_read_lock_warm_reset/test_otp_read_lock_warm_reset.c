/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_read_lock_warm_reset.c
 * @brief OTP_READ_LOCK warm-reset domain verification.
 *
 * Verifies that OTP_READ_LOCK lives in the warm reset domain: a lock applied
 * before a warm reset is cleared by that warm reset, restoring read access to
 * the previously locked OTP field.
 *
 * The test runs across one warm reset using the SRAM-marker phase-detection
 * pattern (see test_warm_reset.c).  A marker word is written to a stable SRAM
 * location (below BSS_START so crt0.s does not clear it on restart) before the
 * warm reset; on restart the firmware reads the marker to select the phase.
 *
 * Phase 0 — cold boot (marker == 0):
 *   1. Drive OTP pattern; verify chiplet_uid is readable.
 *   2. Lock chiplet_uid via OTP_READ_LOCK; verify it now reads zero and the
 *      OTP_READ_LOCK.chiplet_uid bit is set.
 *   3. Write SRAM marker = MARKER_PHASE1.
 *   4. Issue TB_CMD_KM_WARM_RESET → CPU restarts via external warm_rst_n.
 *
 * Phase 1 — after warm reset (marker == MARKER_PHASE1):
 *   1. Verify SRAM marker persists (SRAM is cold-only).
 *   2. Verify OTP_READ_LOCK == 0 (warm reset cleared the warm-domain lock).
 *   3. Re-drive OTP and verify chiplet_uid is readable again (lock gone).
 *   4. TEST_PASS.
 *
 * Run: make run_fw FW_TEST=test_otp_read_lock_warm_reset
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "rom_otp.h"
#include "rom_kmcsr.h"

/* SRAM word used as phase marker.  Must be below BSS_START so crt0.s does not
 * clear it when it re-executes after the warm reset (crt0 only clears .bss).
 * Mirrors the convention in test_warm_reset.c (+0x2C00). */
#define MARKER_ADDR (SRAM_BASE + 0x2C00u)
#define MARKER_PHASE1 0xA5000001u

int main(void) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    int rc;

    TEST_INIT();

    /*
     * Test firmware provides its own main(), so replicate what production
     * rom_boot_init() does and mark COLD_BOOT_DONE at the top of every boot.
     * woset makes this idempotent across the warm restart.
     */
    rom_kmcsr_cold_boot_done_set();

    if (!tb_set_timeout(300000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    volatile uint32_t *marker = (volatile uint32_t *)MARKER_ADDR;
    uint32_t phase = *marker;

    if (phase == 0u) {
        /*====================================================================
         * Phase 0: cold boot — apply lock, then warm reset
         *====================================================================*/
        printf("OTP Read-Lock Warm-Reset Test (Phase 0)\n");
        printf("========================================\n\n");

        /* 1. Drive OTP pattern and confirm chiplet_uid is readable */
        TEST_SUBTEST_START("Phase 0: chiplet_uid readable before lock");
        tb_otp_write();
        test_delay(200);
        rc = rom_otp_read_chiplet_uid(buf);
        if (rc != 0 || (buf[0] == 0 && buf[7] == 0)) {
            TEST_FAIL("chiplet_uid: not readable before lock");
        }
        TEST_SUBTEST_PASS();

        /* 2. Lock chiplet_uid and verify it reads zero + lock bit set */
        TEST_SUBTEST_START("Phase 0: lock chiplet_uid");
        rom_otp_set_read_lock(KM_CSR__OTP_READ_LOCK_REG__CHIPLET_UID_bm);

        if ((ROM_OTP_READ_LOCK_REG.w & KM_CSR__OTP_READ_LOCK_REG__CHIPLET_UID_bm) == 0u) {
            TEST_FAIL("OTP_READ_LOCK.chiplet_uid not set after lock");
        }
        (void)rom_otp_read_chiplet_uid(buf);
        for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
            if (buf[i] != 0u) {
                TEST_FAIL("chiplet_uid[%u]: non-zero after lock (expected 0)", i);
            }
        }
        TEST_SUBTEST_PASS();

        /* 3. Advance phase marker before resetting */
        TEST_SUBTEST_START("Phase 0: warm reset via external warm_rst_n");
        *marker = MARKER_PHASE1;
        __asm__ volatile("fence" ::: "memory");

        /* 4. Request warm reset; CPU restarts and runs Phase 1 */
        if (!tb_km_warm_reset(30000u)) {
            TEST_FAIL("TB_CMD_KM_WARM_RESET failed to be acknowledged");
        }

        /* Should not reach here — CPU restarted by warm reset */
        TEST_FAIL("Execution continued after warm reset");

    } else if (phase == MARKER_PHASE1) {
        /*====================================================================
         * Phase 1: after warm reset — lock must be cleared
         *====================================================================*/
        printf("OTP Read-Lock Warm-Reset Test (Phase 1)\n");
        printf("========================================\n\n");

        /* 1. SRAM marker persisted across the warm reset */
        TEST_SUBTEST_START("Phase 1: SRAM marker persists");
        TEST_ASSERT_EQ(*marker, MARKER_PHASE1, "SRAM marker after warm reset");
        TEST_SUBTEST_PASS();

        /* 2. OTP_READ_LOCK is warm-domain → cleared by the warm reset */
        TEST_SUBTEST_START("Phase 1: OTP_READ_LOCK cleared by warm reset");
        if (ROM_OTP_READ_LOCK_REG.w != 0u) {
            TEST_FAIL("OTP_READ_LOCK not cleared by warm reset: 0x%08X",
                      (unsigned)ROM_OTP_READ_LOCK_REG.w);
        }
        TEST_SUBTEST_PASS();

        /* 3. chiplet_uid is readable again now that the lock is gone */
        TEST_SUBTEST_START("Phase 1: chiplet_uid readable after unlock");
        tb_otp_write();
        test_delay(200);
        rc = rom_otp_read_chiplet_uid(buf);
        if (rc != 0 || (buf[0] == 0 && buf[7] == 0)) {
            TEST_FAIL("chiplet_uid: not readable after warm-reset unlock");
        }
        TEST_SUBTEST_PASS();

        TEST_PASS();

    } else {
        /* Unexpected marker — corrupt SRAM or missing phase */
        TEST_FAIL("Unexpected phase marker: 0x%08X", (unsigned)phase);
    }

    return 0;
}
