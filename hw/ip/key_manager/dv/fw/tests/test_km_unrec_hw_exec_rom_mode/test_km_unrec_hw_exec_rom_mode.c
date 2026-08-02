/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_exec_rom_mode.c
 * @brief Unrecoverable fault test: instruction fetch from SRAM in ROM mode.
 *
 * While SRAM_EXEC_MODE.enable == 0 (ROM mode), instruction fetch from any SRAM
 * address is forbidden.  Verifies that calling a function copied to SRAM triggers
 * the exec-permission whitelist violation and produces fault code ROM_KM_UFAULT_EXEC.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_unrec_hw_exec_rom_mode
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_boot.h"
#include "key_manager_fw.h"

/* Target: an unlocked SRAM address well above the test BSS/stack.
 * Region 24 = 0x4000 + 24*0x200 = 0x7000.  Not locked here. */
#define SRAM_CODE_BASE (SRAM_BASE + 0x3000u)

/* Trivial function to copy to SRAM: returns its argument + 1. */
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

    rom_boot_init(); /* enables exec_violation_en; EXEC_MODE.enable stays 0 (ROM mode) */

    /* Copy function body to SRAM */
    uint32_t fn_size = (uint32_t)((uintptr_t)add1_stub_end - (uintptr_t)add1_stub);
    uint8_t *src = (uint8_t *)(uintptr_t)add1_stub;
    uint8_t *dst = (uint8_t *)SRAM_CODE_BASE;
    for (uint32_t i = 0; i < fn_size; i++) dst[i] = src[i];

    /* Call the SRAM copy.  Since EXEC_MODE.enable == 0, this fetch is
     * outside the whitelist → exec_violation_o fires → UFAULT_EXEC. */
    add1_fn_t fn = (add1_fn_t)SRAM_CODE_BASE;
    volatile uint32_t result = fn(0);
    (void)result;

    TEST_FAIL("CPU did not halt after SRAM fetch in ROM mode");
    return 0;
}
