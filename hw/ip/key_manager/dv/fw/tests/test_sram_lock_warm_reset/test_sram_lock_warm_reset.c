/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_sram_lock_warm_reset.c
 * @brief SRAM write-lock warm-reset domain: lock-then-reset-then-re-lock handover model.
 *
 * Verifies that:
 *   1. SRAM_LOCK is cleared on warm reset (warm reset domain).
 *   2. After warm reset, previously locked regions accept writes again.
 *   3. ROM can re-apply the write-lock policy after each boot (cold and warm)
 *      before handing control to mutable firmware.
 *
 * This test simulates the ROM-managed lock lifecycle:
 *   - ROM applies write-lock before handover.
 *   - Warm reset clears the lock.
 *   - ROM re-applies the lock on the next boot before handover.
 *
 * Phase detection:
 *   A 32-bit marker below BSS_START records which phase is in progress.
 *   Marker at SRAM_BASE + 0x2800 is below the markers used by test_warm_reset.c
 *   (+0x2C00) and test_soft_reset.c (+0x3000) and avoids collision.
 *
 * Phase 0 (cold boot):
 *   1. Lock the test region (simulating ROM pre-handover lock).
 *   2. Verify the lock bit is set in SRAM_LOCK.
 *   3. Attempt a write to the locked region; verify it is dropped.
 *   4. Verify SRAM_WRITE_LOCK_VIOLATION is set.
 *   5. Write phase marker; issue warm reset via TB_CMD_KM_WARM_RESET.
 *
 * Phase 1 (after warm reset — simulating ROM re-entry):
 *   1. Verify SRAM_LOCK == 0 (cleared by warm reset).
 *   2. Write to the previously locked region; verify write succeeds.
 *   3. Re-lock the region (simulating ROM re-establishing lock before handover).
 *   4. Verify the lock bit is set again.
 *   5. Attempt write to the re-locked region; verify it is dropped.
 *   6. Verify SRAM_WRITE_LOCK_VIOLATION is set again.
 *   7. TEST_PASS.
 *
 * Test region selection:
 *   Region 6 covers 0x4C00-0x4DFF — below BSS/data/stack (packed from the top
 *   of SRAM) and not the known hang region (15) or any phase-marker region.
 *   No data/bss/stack is expected at this address for simple firmware tests.
 *
 * Run with:
 *   make run_fw FW_TEST=test_sram_lock_warm_reset
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "rom_kmcsr.h"

/*===========================================================================
 * Constants
 *===========================================================================*/

/* Phase marker: must be below BSS_START so crt0.s does not clear it on
 * warm restart.  Choose a distinct offset from other multi-phase tests. */
#define MARKER_ADDR (SRAM_BASE + 0x2800u)
#define MARKER_PHASE1 0xBB000001u

/* Test SRAM write-lock region.
 * Region 6 = bytes [0x4C00, 0x4DFF] — low SRAM, below any data/bss/stack.
 * Not region 15 (known hang), not a phase-marker region. */
#define TEST_REGION 6u
#define TEST_REGION_MASK (1u << TEST_REGION)
#define TEST_REGION_BASE (SRAM_BASE + (uint32_t)TEST_REGION * 512u)
#define TEST_WRITE_ADDR (TEST_REGION_BASE + 0x80u)

/* Distinct data patterns for before/after lock. */
#define PATTERN_INITIAL 0xABCD0006u
#define PATTERN_DROPPED 0xDEAD0006u  /* Should be silently dropped when locked */
#define PATTERN_UNLOCKED 0x1234ABCDu /* Written after warm reset (region unlocked) */

/*===========================================================================
 * Helpers
 *===========================================================================*/

static void clear_violation_and_irq(void) {
    volatile uint32_t *viol =
        (volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR;
    *viol = 0xFFFFFFFFu; /* W1C: clear all violation bits */

    km_csr__irq_status_reg_t clr = {0};
    clr.f.sram_write_lock_err = 1u;
    KMCSR_IRQ_STATUS_REG.w = clr.w;
}

static uint32_t read_violation(void) {
    volatile uint32_t *viol =
        (volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR;
    return *viol;
}

/*===========================================================================
 * main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    rom_kmcsr_cold_boot_done_set();

    volatile uint32_t *marker = (volatile uint32_t *)MARKER_ADDR;
    volatile uint32_t *test_word = (volatile uint32_t *)TEST_WRITE_ADDR;
    uint32_t phase = *marker;

    if (phase == 0u) {
        /*====================================================================
         * Phase 0: cold boot — simulate ROM applying lock before handover
         *====================================================================*/
        TEST_SUBTEST_START("Phase 0: write initial pattern (region unlocked)");

        /* Write a known pattern while the region is still unlocked. */
        *test_word = PATTERN_INITIAL;
        __asm__ volatile("fence" ::: "memory");
        uint32_t readback = *test_word;
        if (readback != PATTERN_INITIAL) {
            TEST_FAIL("Phase 0: initial write failed (read 0x%08X, expected 0x%08X)",
                      (unsigned)readback, (unsigned)PATTERN_INITIAL);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: lock region (simulating ROM pre-handover lock)");

        clear_violation_and_irq();
        rom_kmcsr_sram_lock_set(TEST_REGION_MASK);
        __asm__ volatile("fence" ::: "memory");

        uint32_t lock_val = rom_kmcsr_sram_lock_read();
        if ((lock_val & TEST_REGION_MASK) == 0u) {
            TEST_FAIL("Phase 0: SRAM_LOCK bit %u not set (read 0x%08X)", (unsigned)TEST_REGION,
                      (unsigned)lock_val);
        }

        /* Write-1-only: writing 0 must not clear the bit. */
        rom_kmcsr_sram_lock_set(0u);
        lock_val = rom_kmcsr_sram_lock_read();
        if ((lock_val & TEST_REGION_MASK) == 0u) {
            TEST_FAIL("Phase 0: SRAM_LOCK bit cleared by write-0 (read 0x%08X)",
                      (unsigned)lock_val);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: write to locked region is dropped");

        *test_word = PATTERN_DROPPED;
        __asm__ volatile("fence" ::: "memory");
        readback = *test_word;
        if (readback != PATTERN_INITIAL) {
            TEST_FAIL("Phase 0: write to locked region not dropped "
                      "(read 0x%08X, expected 0x%08X)",
                      (unsigned)readback, (unsigned)PATTERN_INITIAL);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: violation flag set after locked write");

        uint32_t viol = read_violation();
        if ((viol & TEST_REGION_MASK) == 0u) {
            TEST_FAIL("Phase 0: SRAM_WRITE_LOCK_VIOLATION bit %u not set (reg=0x%08X)",
                      (unsigned)TEST_REGION, (unsigned)viol);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: warm reset via external warm_rst_n");

        *marker = MARKER_PHASE1;
        __asm__ volatile("fence" ::: "memory");

        if (!tb_km_warm_reset(5000u)) {
            TEST_FAIL("TB_CMD_KM_WARM_RESET not acknowledged");
        }

        /* Should not reach here. */
        TEST_FAIL("Execution continued after warm reset");

    } else if (phase == MARKER_PHASE1) {
        /*====================================================================
         * Phase 1: after warm reset — simulate ROM re-entry and re-lock
         *====================================================================*/
        TEST_SUBTEST_START("Phase 1: SRAM_LOCK cleared by warm reset");

        uint32_t lock_val = rom_kmcsr_sram_lock_read();
        if (lock_val != 0u) {
            TEST_FAIL("Phase 1: SRAM_LOCK not cleared by warm reset (read 0x%08X)",
                      (unsigned)lock_val);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: write to previously-locked region succeeds");

        /* Region is now unlocked; write a new pattern and verify it lands. */
        *test_word = PATTERN_UNLOCKED;
        __asm__ volatile("fence" ::: "memory");
        uint32_t readback = *test_word;
        if (readback != PATTERN_UNLOCKED) {
            TEST_FAIL("Phase 1: write after warm reset failed "
                      "(read 0x%08X, expected 0x%08X)",
                      (unsigned)readback, (unsigned)PATTERN_UNLOCKED);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START(
            "Phase 1: re-lock region (simulating ROM re-applying policy before handover)");

        clear_violation_and_irq();
        rom_kmcsr_sram_lock_set(TEST_REGION_MASK);
        __asm__ volatile("fence" ::: "memory");

        lock_val = rom_kmcsr_sram_lock_read();
        if ((lock_val & TEST_REGION_MASK) == 0u) {
            TEST_FAIL("Phase 1: SRAM_LOCK bit %u not set after re-lock (read 0x%08X)",
                      (unsigned)TEST_REGION, (unsigned)lock_val);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: write to re-locked region is dropped");

        *test_word = PATTERN_DROPPED;
        __asm__ volatile("fence" ::: "memory");
        readback = *test_word;
        if (readback != PATTERN_UNLOCKED) {
            TEST_FAIL("Phase 1: write to re-locked region not dropped "
                      "(read 0x%08X, expected 0x%08X)",
                      (unsigned)readback, (unsigned)PATTERN_UNLOCKED);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: violation flag set after re-locked write");

        uint32_t viol = read_violation();
        if ((viol & TEST_REGION_MASK) == 0u) {
            TEST_FAIL(
                "Phase 1: SRAM_WRITE_LOCK_VIOLATION bit %u not set after re-lock (reg=0x%08X)",
                (unsigned)TEST_REGION, (unsigned)viol);
        }

        TEST_SUBTEST_PASS();

        TEST_PASS();

    } else {
        TEST_FAIL("Unexpected phase marker: 0x%08X", (unsigned)phase);
    }

    return 0;
}
