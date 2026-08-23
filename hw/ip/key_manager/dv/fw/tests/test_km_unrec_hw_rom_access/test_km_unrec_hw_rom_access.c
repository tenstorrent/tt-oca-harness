/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_rom_access.c
 * @brief Unrecoverable fault test: ROM_ACCESS_VIOLATION
 *
 * Uses KMCSR IRQ_SET to assert ROM_ACCESS_VIOLATION and verifies the firmware
 * takes the unrecoverable path with ROM_KM_UFAULT_ROM_ACCESS.
 *
 * The bit is driven by software here rather than by an actual lockout breach,
 * because a real breach leaves the ROM ISR itself unreachable: this is the only
 * path on which the fault code reaches the SEP mailbox, and the point of the
 * test is to prove the decode and reporting are wired up.  The blocked-access
 * behaviour is covered by test_km_exec_sram_locked_ok and the
 * test_km_rom_lockout_* handover tests.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_unrec_hw_rom_access
 */

#include "test_common.h"
#include "rom_defs.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

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
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_ROM_ACCESS) {
            TEST_FAIL("Wrong fault code: expected ROM_KM_UFAULT_ROM_ACCESS");
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

    rom_boot_init();

    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.rom_access_violation_set = 1;
    rom_kmcsr_irq_set(set_val.w);

    TEST_FAIL("CPU did not halt after ROM access violation");
    return 0;
}
