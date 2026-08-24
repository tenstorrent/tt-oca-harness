/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_drbg_slverr.c
 * @brief Unrecoverable fault test: DRBG_ERR is reported ahead of AXI_SLVERR
 *
 * Stops the DRBG source and reads DATA, so the sampler exhausts CFG.TIMEOUT and
 * answers the read with SLVERR while pulsing drbg_error_o. IRQ_STATUS.AXI_SLVERR
 * and IRQ_STATUS.DRBG_ERR therefore arrive together, as they do when entropy runs
 * out in a real system, and the firmware must report the specific
 * ROM_KM_UFAULT_DRBG_ERR rather than the generic ROM_KM_UFAULT_AXI_SLVERR.
 */

#include "test_common.h"
#include "rom_defs.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DRBG Sampler registers */
#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)

/* Reads attempted against the stopped source. The first may still be served from a
 * word prefetched before the stop, so more than one is needed to reach the timeout. */
#define STARVED_READS 4u

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

    /* CFG.TIMEOUT keeps its reset value so the sampler times out on the same budget
     * production uses; prefetch is cleared so no fetch is started behind the read. */
    km_drbg_sampler__cfg_reg_t cfg = {.w = DRBG_CFG_REG.w};
    cfg.f.prefetch = 0;
    DRBG_CFG_REG.w = cfg.w;

    if (!tb_drbg_stop(1000)) {
        TEST_FAIL("tb_drbg_stop failed");
    }

    for (uint32_t i = 0; i < STARVED_READS; i++) {
        volatile uint32_t discard = DRBG_DATA_REG.w;
        (void)discard;
    }

    TEST_FAIL("CPU did not halt after DRBG timeout");
    return 0;
}
