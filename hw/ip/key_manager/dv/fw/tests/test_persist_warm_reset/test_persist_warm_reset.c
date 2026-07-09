/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_persist_warm_reset.c
 * @brief ROM warm-persist region (rom_persist): cold-init and warm-reset survival.
 *
 * Verifies that:
 *   1. rom_persist_cold_init() zeroes sram_fw_size on cold boot.
 *   2. A value written to rom_persist.sram_fw_size survives a warm reset
 *      (SRAM storage is cold-domain; only a cold reset clears it).
 *   3. rom_boot_init's cold-only gate (COLD_BOOT_DONE) ensures cold-init is
 *      NOT re-run on warm boot, leaving the persisted value intact.
 *   4. rom_persist_lock() sets SRAM_LOCK bit 31 and a subsequent write attempt
 *      to the persist region is silently dropped (violation flag raised).
 *
 * Phase detection:
 *   A 32-bit marker below BSS_START records which phase is in progress.
 *   Marker at SRAM_BASE + 0x2400 is distinct from other multi-phase tests:
 *     test_warm_reset.c           (+0x2C00)
 *     test_irq_entry_reset_restore (+0x2E00)
 *     test_soft_reset.c           (+0x3000)
 *
 * Phase 0 (cold boot, marker == 0):
 *   1. Call rom_persist_cold_init() — simulates cold-boot-only initialization.
 *   2. Verify sram_fw_size == 0.
 *   3. Set sram_fw_size = SENTINEL_SIZE (a non-zero value).
 *   4. Verify readback == SENTINEL_SIZE.
 *   5. Set COLD_BOOT_DONE — mirrors rom_boot_init's end-of-boot marker.
 *   6. Write phase marker; issue warm reset via TB_CMD_KM_WARM_RESET.
 *
 * Phase 1 (after warm reset, marker == MARKER_PHASE1):
 *   1. Verify COLD_BOOT_DONE == 1 (ROM re-sets it on every boot).
 *   2. Verify sram_fw_size == SENTINEL_SIZE (survived warm reset, not re-zeroed).
 *   3. Call rom_persist_lock(); verify SRAM_LOCK bit 31 is set.
 *   4. Attempt write via rom_persist_set_sram_fw_size(); verify write dropped.
 *   5. Verify SRAM_WRITE_LOCK_VIOLATION bit 31 is set.
 *   6. TEST_PASS.
 *
 * Run with:
 *   make run_fw FW_TEST=test_persist_warm_reset
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_persist.h"
#include "rom_kmcsr.h"

/*===========================================================================
 * Constants
 *===========================================================================*/

/* Phase marker: must be below BSS_START so crt0.s does not clear it on warm
 * restart.  Use a distinct offset from other multi-phase tests. */
#define MARKER_ADDR (SRAM_BASE + 0x2400u)
#define MARKER_PHASE1 0xCC000001u

/* Sentinel sram_fw_size written in Phase 0 and verified in Phase 1.
 * A plausible-looking byte count distinct from 0 and easy to spot in traces. */
#define SENTINEL_SIZE 0x00001800u /* 6 KB — representative SRAM image size */

/* Value used to attempt a write into the locked persist region. Must differ
 * from SENTINEL_SIZE so a successful (bad) write would be detectable. */
#define LOCK_WRITE_ATTEMPT 0xDEADBEEFu

/*===========================================================================
 * Helpers
 *===========================================================================*/

static void clear_violation(void) {
    volatile uint32_t *viol =
        (volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR;
    *viol = 0xFFFFFFFFu; /* W1C: clear all violation bits */
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

    volatile uint32_t *marker = (volatile uint32_t *)MARKER_ADDR;
    uint32_t phase = *marker;

    if (phase == 0u) {
        /*====================================================================
         * Phase 0: cold boot
         *====================================================================*/

        TEST_SUBTEST_START("Phase 0: cold-init zeroes sram_fw_size");

        rom_persist_cold_init();
        __asm__ volatile("fence" ::: "memory");

        uint32_t sz = rom_persist_get_sram_fw_size();
        if (sz != 0u) {
            TEST_FAIL("Phase 0: sram_fw_size not zeroed by cold_init (got 0x%08X)", (unsigned)sz);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: set and readback sentinel sram_fw_size");

        rom_persist_set_sram_fw_size(SENTINEL_SIZE);
        __asm__ volatile("fence" ::: "memory");

        sz = rom_persist_get_sram_fw_size();
        if (sz != SENTINEL_SIZE) {
            TEST_FAIL("Phase 0: readback mismatch (got 0x%08X, expected 0x%08X)", (unsigned)sz,
                      (unsigned)SENTINEL_SIZE);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: warm reset via external warm_rst_n");

        /* Mirror rom_boot_init's end-of-boot marker so Phase 1 can verify it. */
        rom_kmcsr_cold_boot_done_set();

        *marker = MARKER_PHASE1;
        __asm__ volatile("fence" ::: "memory");

        if (!tb_km_warm_reset(5000u)) {
            TEST_FAIL("TB_CMD_KM_WARM_RESET not acknowledged");
        }

        /* Should not reach here. */
        TEST_FAIL("Execution continued after warm reset");

    } else if (phase == MARKER_PHASE1) {
        /*====================================================================
         * Phase 1: after warm reset — verify sentinel survived
         *====================================================================*/

        TEST_SUBTEST_START("Phase 1: COLD_BOOT_DONE == 1 after warm reset");

        if (!rom_kmcsr_cold_boot_done_read()) {
            TEST_FAIL("Phase 1: COLD_BOOT_DONE not set after warm reset");
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: sram_fw_size survived warm reset");

        uint32_t sz = rom_persist_get_sram_fw_size();
        if (sz != SENTINEL_SIZE) {
            TEST_FAIL("Phase 1: sram_fw_size did not survive warm reset "
                      "(got 0x%08X, expected 0x%08X)",
                      (unsigned)sz, (unsigned)SENTINEL_SIZE);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: rom_persist_lock() sets SRAM_LOCK bit 31");

        clear_violation();
        rom_persist_lock();
        __asm__ volatile("fence" ::: "memory");

        uint32_t lock_val = rom_kmcsr_sram_lock_read();
        if ((lock_val & ROM_KM_PERSIST_LOCK_MASK) == 0u) {
            TEST_FAIL("Phase 1: SRAM_LOCK bit 31 not set after rom_persist_lock() "
                      "(SRAM_LOCK=0x%08X)",
                      (unsigned)lock_val);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: write to locked persist region is dropped");

        rom_persist_set_sram_fw_size(LOCK_WRITE_ATTEMPT);
        __asm__ volatile("fence" ::: "memory");

        uint32_t after = rom_persist_get_sram_fw_size();
        if (after != sz) {
            TEST_FAIL("Phase 1: write to locked region was NOT dropped "
                      "(got 0x%08X, expected 0x%08X)",
                      (unsigned)after, (unsigned)sz);
        }

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 1: SRAM_WRITE_LOCK_VIOLATION bit 31 set after locked write");

        uint32_t viol = read_violation();
        if ((viol & ROM_KM_PERSIST_LOCK_MASK) == 0u) {
            TEST_FAIL("Phase 1: SRAM_WRITE_LOCK_VIOLATION bit 31 not set "
                      "(reg=0x%08X)",
                      (unsigned)viol);
        }

        TEST_SUBTEST_PASS();

        TEST_PASS();

    } else {
        TEST_FAIL("Unexpected phase marker: 0x%08X", (unsigned)phase);
    }

    return 0;
}
