/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_drbg_slverr.c
 * @brief Unrecoverable fault test: DRBG_ERR is reported ahead of AXI_SLVERR
 *
 * A DRBG timeout answers the CPU's DATA read with SLVERR and pulses
 * drbg_error_o in the same cycle, so IRQ_STATUS.AXI_SLVERR and
 * IRQ_STATUS.DRBG_ERR are always set together. Uses KMCSR IRQ_SET to assert
 * both in a single write and verifies the firmware reports the specific
 * ROM_KM_UFAULT_DRBG_ERR rather than the generic ROM_KM_UFAULT_AXI_SLVERR.
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
        if (fault_code == (uint32_t)(int32_t)ROM_KM_UFAULT_AXI_SLVERR) {
            TEST_FAIL("Reported AXI_SLVERR: DRBG_ERR must win when both are set");
        }
        if (fault_code != (uint32_t)(int32_t)ROM_KM_UFAULT_DRBG_ERR) {
            TEST_FAIL("Wrong fault code: expected DRBG_ERR");
        }
        TEST_PASS();
        return 0;
    }

    if (!tb_set_timeout(500000) || !tb_drbg_set_seed(0xD8E2u, 5000)) {
        TEST_FAIL("TB setup failed");
    }

    if (!tb_set_unrecoverable_watch(1, 1000u)) {
        TEST_FAIL("Failed to arm unrecoverable watcher");
    }

    rom_boot_init();

    /* One write so both sticky bits land together, as the hardware sets them. */
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.axi_slverr_set = 1;
    set_val.f.drbg_err_set = 1;
    rom_kmcsr_irq_set(set_val.w);

    TEST_FAIL("CPU did not halt after DRBG error with SLVERR");
    return 0;
}
