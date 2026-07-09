/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_bus_error.c
 * @brief Unrecoverable fault test: BUS_ERROR
 *
 * Executes a misaligned word load to provoke PicoRV32 BUSERR IRQ and
 * verifies ROM_KM_UFAULT_BUS_ERROR after testbench restart.
 */

#include "test_common.h"
#include "rom_defs.h"

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
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_BUS_ERROR) {
            TEST_FAIL("Wrong fault code: expected BUS_ERROR");
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

    __asm__ volatile("li t0, 0x00004001\n"
                     "lw t1, 0(t0)\n"
                     :
                     :
                     : "t0", "t1", "memory");

    TEST_FAIL("CPU did not halt after bus error trap");
    return 0;
}
