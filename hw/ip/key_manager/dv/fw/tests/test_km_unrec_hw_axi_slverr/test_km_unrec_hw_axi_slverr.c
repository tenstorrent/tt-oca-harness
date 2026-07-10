/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_axi_slverr.c
 * @brief Unrecoverable fault test: AXI_SLVERR
 *
 * Writes to an unmapped register inside KMCSR's range to provoke AXI
 * SLVERR and verifies ROM_KM_UFAULT_AXI_SLVERR after restart.
 */

#include "test_common.h"
#include "rom_defs.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define KMCSR_UNMAPPED_REG_ADDR (KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR - 4u)

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
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_AXI_SLVERR) {
            TEST_FAIL("Wrong fault code: expected AXI_SLVERR");
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

    *(volatile uint32_t *)KMCSR_UNMAPPED_REG_ADDR = 0xA5A5A5A5u;

    TEST_FAIL("CPU did not halt after AXI SLVERR");
    return 0;
}
