/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_exec_periph.c
 * @brief Unrecoverable fault test: instruction fetch from peripheral/AXI space.
 *
 * Peripheral/AXI space (addresses outside ROM, SRAM, and VROM) is never in the
 * execute-permission whitelist regardless of SRAM_EXEC_MODE.  Verifies that a
 * function-pointer call to a KMCSR register address triggers fault code
 * ROM_KM_UFAULT_EXEC.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_unrec_hw_exec_periph
 */

#include "test_common.h"
#include "rom_defs.h"
#include "rom_boot.h"
#include "key_manager_fw.h"

/* Use KEY_MANAGER_KMCSR_VERSION_BASE_ADDR (0x0000_E000) as the illegal target.
 * This address is in peripheral/AXI space — always non-executable. */
#define PERIPH_EXEC_TARGET KEY_MANAGER_KMCSR_VERSION_BASE_ADDR

typedef void (*void_fn_t)(void);

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

    /* Attempt instruction fetch from KMCSR peripheral space.
     * is_rom_addr = is_vrom_addr = is_sram_addr = 0 → exec_allowed = 0
     * → exec_violation fires → UFAULT_EXEC. */
    void_fn_t fn = (void_fn_t)PERIPH_EXEC_TARGET;
    fn();

    TEST_FAIL("CPU did not halt after fetch from peripheral space");
    return 0;
}
