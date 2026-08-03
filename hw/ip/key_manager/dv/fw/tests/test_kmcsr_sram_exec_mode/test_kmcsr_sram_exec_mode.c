/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kmcsr_sram_exec_mode.c
 * @brief SRAM_EXEC_MODE register semantics test.
 *
 * Verifies KMCSR SRAM_EXEC_MODE register behavior:
 *   1. Reads 0 at reset (warm-reset domain, write-1-only).
 *   2. Write-0 is a no-op (woset semantics).
 *   3. Write-1 sets the enable bit.
 *   4. Triple-write idempotency (re-writing 1 has no side-effects).
 *   5. Write-0 after set is still a no-op.
 *   6. Bit is cleared by warm reset (two-phase test via rom_persist).
 *
 * Phase detection: sram_fw_size == 0 → Phase 0 (cold boot).
 *                 sram_fw_size != 0 → Phase 1 (after warm reset).
 *
 * Run with:
 *   make run_fw FW_TEST=test_kmcsr_sram_exec_mode
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "rom_kmcsr.h"
#include "rom_boot.h"
#include "rom_persist.h"

#define EXEC_MODE_REG \
    (*(volatile km_csr__sram_exec_mode_reg_t *)KEY_MANAGER_KMCSR_SRAM_EXEC_MODE_BASE_ADDR)

#define WARM_RESET_MARKER 4u /* non-zero sram_fw_size used as phase indicator */

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000) || !tb_drbg_set_seed(0xFA12u, 5000)) {
        TEST_FAIL("TB setup failed");
    }

    rom_boot_init();

    /* ------------------------------------------------------------------ */
    /* Phase 1: after warm reset, verify EXEC_MODE.enable == 0.            */
    /* ------------------------------------------------------------------ */
    if (rom_persist_get_sram_fw_size() != 0) {
        rom_persist_set_sram_fw_size(0u);

        TEST_SUBTEST_START("enable cleared by warm reset");
        TEST_ASSERT_EQ(EXEC_MODE_REG.f.enable, 0u,
                       "SRAM_EXEC_MODE.enable must be 0 after warm reset");
        TEST_SUBTEST_PASS();

        TEST_PASS();
        return 0;
    }

    /* ------------------------------------------------------------------ */
    /* Phase 0: cold boot — register semantics tests.                      */
    /* ------------------------------------------------------------------ */

    /* Test 1: reads 0 at cold reset */
    TEST_SUBTEST_START("reads 0 at cold reset");
    TEST_ASSERT_EQ(EXEC_MODE_REG.f.enable, 0u, "SRAM_EXEC_MODE.enable must be 0 after cold reset");
    TEST_SUBTEST_PASS();

    /* Test 2: write-0 is a no-op */
    TEST_SUBTEST_START("write-0 is no-op");
    {
        km_csr__sram_exec_mode_reg_t w = {0};
        w.f.enable = 0u;
        EXEC_MODE_REG.w = w.w;
    }
    TEST_ASSERT_EQ(EXEC_MODE_REG.f.enable, 0u, "still 0 after write-0");
    TEST_SUBTEST_PASS();

    /* Test 3: write-1 sets enable (triple write via helper) */
    TEST_SUBTEST_START("write-1 sets enable");
    rom_kmcsr_sram_exec_mode_set();
    TEST_ASSERT_EQ(EXEC_MODE_REG.f.enable, 1u, "enable == 1 after write-1");
    TEST_SUBTEST_PASS();

    /* Test 4: triple-write idempotency */
    TEST_SUBTEST_START("triple-write idempotency");
    rom_kmcsr_sram_exec_mode_set();
    rom_kmcsr_sram_exec_mode_set();
    TEST_ASSERT_EQ(EXEC_MODE_REG.f.enable, 1u, "still 1 after repeated writes");
    TEST_SUBTEST_PASS();

    /* Test 5: write-0 after set is still a no-op */
    TEST_SUBTEST_START("write-0 after set is no-op");
    {
        km_csr__sram_exec_mode_reg_t w = {0};
        w.f.enable = 0u;
        EXEC_MODE_REG.w = w.w;
    }
    TEST_ASSERT_EQ(EXEC_MODE_REG.f.enable, 1u, "still 1 after write-0 attempt");
    TEST_SUBTEST_PASS();

    /* Mark phase and issue warm reset for test 6 */
    rom_persist_set_sram_fw_size(WARM_RESET_MARKER);
    if (!tb_send_cmd(TB_CMD_KM_WARM_RESET, 0, 50000)) {
        TEST_FAIL("Warm reset command failed");
    }
    TEST_FAIL("Did not restart after warm reset");
    return 0;
}
