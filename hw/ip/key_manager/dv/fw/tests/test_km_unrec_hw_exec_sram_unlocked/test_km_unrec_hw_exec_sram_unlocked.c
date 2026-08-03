/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_exec_sram_unlocked.c
 * @brief Unrecoverable fault test: instruction fetch from unlocked SRAM in SRAM mode.
 *
 * With SRAM_EXEC_MODE.enable == 1 (SRAM mode), instruction fetch from a
 * non-write-locked SRAM region is forbidden (only write-locked regions are
 * in the whitelist).  Verifies that calling a function in an unlocked region
 * triggers fault code ROM_KM_UFAULT_EXEC.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_unrec_hw_exec_sram_unlocked
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_boot.h"
#include "rom_kmcsr.h"
#include "key_manager_fw.h"

/* Use region 18 (0x4000 + 18*0x200 = 0x6400) — intentionally NOT locked. */
#define UNLOCKED_CODE_REGION 18u
#define REGION_SIZE_BYTES 0x200u
#define SRAM_CODE_BASE (SRAM_BASE + (UNLOCKED_CODE_REGION * REGION_SIZE_BYTES))

typedef uint32_t (*add1_fn_t)(uint32_t);

__attribute__((noinline)) static uint32_t add1_stub(uint32_t x) {
    return x + 1u;
}
__attribute__((noinline)) static void add1_stub_end(void) {
    __asm__ volatile("");
}

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    if (tb_check_unrecoverable_restart(1000)) {
        uint32_t fault_code;
        if (!tb_get_unrecoverable_fault_code(1000, &fault_code)) {
            TEST_FAIL("Failed to get unrecoverable fault code");
        }
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_EXEC) {
            TEST_FAIL("Wrong fault code: expected ROM_KM_UFAULT_EXEC");
        }
        TEST_PASS();
        return 0;
    }

    if (!tb_set_timeout(500000) || !tb_drbg_set_seed(0xFA12u, 5000)) {
        TEST_FAIL("TB setup failed");
    }

    if (!tb_set_unrecoverable_watch(1, 1000u)) {
        TEST_FAIL("Failed to arm unrecoverable watcher");
    }

    rom_boot_init(); /* enables exec_violation_en */

    /* Enable SRAM execution mode.  From this point locked SRAM is executable;
     * unlocked SRAM (including region 18) remains forbidden. */
    rom_kmcsr_sram_exec_mode_set();

    /* Copy function to unlocked region 18 — do not call rom_kmcsr_sram_lock_set
     * for this region. */
    uint32_t fn_size = (uint32_t)((uintptr_t)add1_stub_end - (uintptr_t)add1_stub);
    uint8_t *src = (uint8_t *)(uintptr_t)add1_stub;
    uint8_t *dst = (uint8_t *)SRAM_CODE_BASE;
    for (uint32_t i = 0; i < fn_size; i++) dst[i] = src[i];

    /* Call the unlocked copy.  exec_allowed = is_sram_addr && sram_exec_mode_i &&
     * sram_lock_bits_i[18] = 0 → exec_violation fires → UFAULT_EXEC. */
    add1_fn_t fn = (add1_fn_t)SRAM_CODE_BASE;
    volatile uint32_t result = fn(0);
    (void)result;

    TEST_FAIL("CPU did not halt after fetch from unlocked SRAM in SRAM mode");
    return 0;
}
