/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_rom_write.c
 * @brief Unrecoverable fault test: ROM_WRITE
 *
 * Performs an illegal write to ROM and verifies the unrecoverable fault
 * code ROM_KM_UFAULT_ROM_WRITE after testbench-driven restart.
 */

#include "test_common.h"
#include "rom_defs.h"

#define ROM_TEST_ADDR (ROM_BASE + ROM_TEST_OFFSET)

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
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_ROM_WRITE) {
            TEST_FAIL("Wrong fault code: expected ROM_WRITE");
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

    *(volatile uint32_t *)ROM_TEST_ADDR = 0xDEADBEEFu;

    TEST_FAIL("CPU did not halt after ROM write error");
    return 0;
}
