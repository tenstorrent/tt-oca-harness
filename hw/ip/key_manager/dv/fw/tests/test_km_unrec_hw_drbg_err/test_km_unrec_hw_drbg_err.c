/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_drbg_err.c
 * @brief Unrecoverable fault test: DRBG_ERR
 *
 * Uses KMCSR IRQ_SET to assert DRBG_ERR and verifies the firmware takes
 * the unrecoverable path with ROM_KM_UFAULT_DRBG_ERR.
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
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_DRBG_ERR) {
            TEST_FAIL("Wrong fault code: expected DRBG_ERR");
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
    set_val.f.drbg_err_set = 1;
    rom_kmcsr_irq_set(set_val.w);

    TEST_FAIL("CPU did not halt after DRBG error");
    return 0;
}
