/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_sram_write_lock.c
 * @brief Unrecoverable fault test: SRAM_WRITE_LOCK
 *
 * Locks one SRAM region, writes into that region, and verifies the
 * unrecoverable fault code ROM_KM_UFAULT_SRAM_WRITE_LOCK after restart.
 */

#include "test_common.h"
#include "rom_defs.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define SRAM_LOCK_REG (*(volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR)
#define LOCK_REGION 4u
#define REGION_SIZE_BYTES 0x200u
#define LOCKED_ADDR (SRAM_BASE + (LOCK_REGION * REGION_SIZE_BYTES))

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
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_SRAM_WRITE_LOCK) {
            TEST_FAIL("Wrong fault code: expected SRAM_WRITE_LOCK");
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

    SRAM_LOCK_REG = (1u << LOCK_REGION);
    *(volatile uint32_t *)LOCKED_ADDR = 0x11223344u;

    TEST_FAIL("CPU did not halt after SRAM write-lock violation");
    return 0;
}
