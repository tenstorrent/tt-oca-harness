/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_otp_read_lock_cold_warm_reset.c
 * @brief OTP_READ_LOCK_COLD warm-reset persistence test.
 *
 * Verifies the fundamental behavioural difference between the warm-reset-domain
 * (OTP_READ_LOCK) and cold-reset-domain (OTP_READ_LOCK_COLD) read-lock registers:
 * a cold-domain lock survives warm reset while a warm-domain lock is cleared.
 *
 * The test runs across one warm reset using the SRAM-marker phase-detection
 * pattern (see test_warm_reset.c).  A marker word is written to a stable SRAM
 * location (below BSS_START so crt0.s does not clear it on restart) before the
 * warm reset; on restart the firmware reads the marker to select the phase.
 *
 * One secret and one public identity field are locked in each domain, so the
 * identity lock bits are exercised on both sides of the reset.
 *
 * Phase 0 — cold boot (marker == 0):
 *   1. Drive OTP pattern; verify the fields to be warm-locked (chiplet_uid,
 *      sep_chiplet_id) and cold-locked (sip_uid, sep_sys_id) are readable.
 *   2. Set the warm locks (via rom_otp_set_read_lock).
 *      Set the cold locks (via rom_otp_set_read_lock_cold driver; the mailbox
 *      TX path is not initialised without rom_boot_init() and the command-path
 *      is already covered by test_km_cmd_otp_read_lock_cold).
 *   3. Verify all four fields now read all-zero.
 *   4. Write SRAM marker = MARKER_PHASE1.
 *   5. Issue TB_CMD_KM_WARM_RESET → CPU restarts.
 *
 * Phase 1 — after warm reset (marker == MARKER_PHASE1):
 *   1. Verify SRAM marker persisted.
 *   2. Verify OTP_READ_LOCK == 0 (warm domain cleared by warm reset).
 *      Verify OTP_READ_LOCK_COLD still has both cold bits set.
 *   3. Re-drive OTP data and verify:
 *      - the warm-locked fields are readable again.
 *      - the cold-locked fields still read all-zero.
 *   4. TEST_PASS.
 *
 * Run: make run_fw FW_TEST=test_otp_read_lock_cold_warm_reset
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_boot.h"
#include "rom_otp.h"
#include "rom_kmcsr.h"
#include "key_manager_fw.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

/* SRAM phase marker.  Must be below BSS_START so crt0.s does not clear it on
 * warm reset (crt0 only zeroes .bss).  Convention mirrors test_warm_reset.c. */
#define MARKER_ADDR (SRAM_BASE + 0x2C10u)
#define MARKER_PHASE1 0xA5000002u

#define WARM_LOCK_BITS \
    (KM_CSR__OTP_READ_LOCK_REG__CHIPLET_UID_bm | KM_CSR__OTP_READ_LOCK_REG__SEP_CHIPLET_ID_bm)
#define COLD_LOCK_BITS \
    (KM_CSR__OTP_READ_LOCK_COLD_REG__SIP_UID_bm | KM_CSR__OTP_READ_LOCK_COLD_REG__SEP_SYS_ID_bm)

static void check_readable(const char *name, int (*reader)(uint32_t[ROM_KM_OTP_WORDS])) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    if (reader(buf) != 0 || (buf[0] == 0u && buf[7] == 0u)) {
        TEST_FAIL("%s: not readable", name);
    }
}

static void check_locked(const char *name, int (*reader)(uint32_t[ROM_KM_OTP_WORDS])) {
    uint32_t buf[ROM_KM_OTP_WORDS];
    (void)reader(buf);
    for (unsigned i = 0; i < ROM_KM_OTP_WORDS; i++) {
        if (buf[i] != 0u) {
            TEST_FAIL("%s[%u]: 0x%08X — read lock did not mask the field", name, i,
                      (unsigned)buf[i]);
        }
    }
}

/*===========================================================================
 * Test body
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    /*
     * Replicate production boot mark (warm-reset safe: woset is idempotent).
     */
    rom_kmcsr_cold_boot_done_set();

    if (!tb_set_timeout(500000)) TEST_FAIL("Failed to set testbench timeout");

    volatile uint32_t *marker = (volatile uint32_t *)MARKER_ADDR;
    uint32_t phase = *marker;

    if (phase == 0u) {
        /*====================================================================
         * Phase 0: cold boot
         *====================================================================*/
        printf("OTP_READ_LOCK_COLD Warm-Reset Persistence Test (Phase 0)\n");
        printf("==========================================================\n\n");

        /* 1. Drive OTP; verify all target fields readable before locking */
        TEST_SUBTEST_START("Phase 0: lock targets readable pre-lock");
        tb_otp_write();
        test_delay(200);
        check_readable("chiplet_uid", rom_otp_read_chiplet_uid);
        check_readable("sep_chiplet_id", rom_otp_read_sep_chiplet_id);
        check_readable("sip_uid", rom_otp_read_sip_uid);
        check_readable("sep_sys_id", rom_otp_read_sep_sys_id);
        TEST_SUBTEST_PASS();

        /* 2. Apply the warm locks and the cold locks.
         *    Cold locks are set via the driver (not the mailbox command); the
         *    mailbox TX path is not initialised without rom_boot_init(), and
         *    end-to-end command testing is covered by test_km_cmd_otp_read_lock_cold. */
        TEST_SUBTEST_START("Phase 0: apply warm and cold locks");
        rom_otp_set_read_lock(WARM_LOCK_BITS);
        TEST_ASSERT((ROM_OTP_READ_LOCK_REG.w & WARM_LOCK_BITS) == WARM_LOCK_BITS,
                    "warm lock bits not set");

        rom_otp_set_read_lock_cold(COLD_LOCK_BITS);
        TEST_ASSERT((ROM_OTP_READ_LOCK_COLD_REG.w & COLD_LOCK_BITS) == COLD_LOCK_BITS,
                    "cold lock bits not set");
        TEST_SUBTEST_PASS();

        /* 3. All locked fields read all-zero */
        TEST_SUBTEST_START("Phase 0: all locked fields read zero");
        check_locked("chiplet_uid", rom_otp_read_chiplet_uid);
        check_locked("sep_chiplet_id", rom_otp_read_sep_chiplet_id);
        check_locked("sip_uid", rom_otp_read_sip_uid);
        check_locked("sep_sys_id", rom_otp_read_sep_sys_id);
        TEST_SUBTEST_PASS();

        /* 4. Advance phase marker, then warm reset */
        TEST_SUBTEST_START("Phase 0: warm reset via external warm_rst_n");
        *marker = MARKER_PHASE1;
        __asm__ volatile("fence" ::: "memory");
        if (!tb_km_warm_reset(30000u)) TEST_FAIL("TB_CMD_KM_WARM_RESET not acknowledged");

        /* CPU restarts — should not reach here */
        TEST_FAIL("Execution continued after warm reset");

    } else if (phase == MARKER_PHASE1) {
        /*====================================================================
         * Phase 1: after warm reset
         *====================================================================*/
        printf("OTP_READ_LOCK_COLD Warm-Reset Persistence Test (Phase 1)\n");
        printf("==========================================================\n\n");

        /* 1. SRAM marker persisted */
        TEST_SUBTEST_START("Phase 1: SRAM marker persists across warm reset");
        TEST_ASSERT_EQ(*marker, MARKER_PHASE1, "SRAM marker after warm reset");
        TEST_SUBTEST_PASS();

        /* 2. Register state after warm reset:
         *    - OTP_READ_LOCK (warm domain) must be 0.
         *    - OTP_READ_LOCK_COLD (cold domain) must still hold both bits. */
        TEST_SUBTEST_START("Phase 1: warm locks cleared; cold locks persist");
        if (ROM_OTP_READ_LOCK_REG.w != 0u) {
            TEST_FAIL("OTP_READ_LOCK not cleared by warm reset: 0x%08X",
                      (unsigned)ROM_OTP_READ_LOCK_REG.w);
        }
        if ((ROM_OTP_READ_LOCK_COLD_REG.w & COLD_LOCK_BITS) != COLD_LOCK_BITS) {
            TEST_FAIL("OTP_READ_LOCK_COLD cleared by warm reset (should persist): 0x%08X",
                      (unsigned)ROM_OTP_READ_LOCK_COLD_REG.w);
        }
        TEST_SUBTEST_PASS();

        /* 3a. The warm-locked fields are readable again */
        TEST_SUBTEST_START("Phase 1: warm-locked fields readable after warm reset");
        tb_otp_write();
        test_delay(200);
        check_readable("chiplet_uid", rom_otp_read_chiplet_uid);
        check_readable("sep_chiplet_id", rom_otp_read_sep_chiplet_id);
        TEST_SUBTEST_PASS();

        /* 3b. The cold-locked fields still read all-zero */
        TEST_SUBTEST_START("Phase 1: cold-locked fields still masked");
        check_locked("sip_uid", rom_otp_read_sip_uid);
        check_locked("sep_sys_id", rom_otp_read_sep_sys_id);
        TEST_SUBTEST_PASS();

        TEST_PASS();

    } else {
        TEST_FAIL("Unexpected phase marker: 0x%08X", (unsigned)phase);
    }

    return 0;
}
