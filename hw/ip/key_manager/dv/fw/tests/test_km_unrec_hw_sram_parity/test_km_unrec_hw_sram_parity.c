/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_hw_sram_parity.c
 * @brief Unrecoverable fault test: SRAM_PARITY
 *
 * Injects an SRAM parity error via the testbench, then reads from SRAM to
 * trigger the fault. The production ISR detects KMCSR_IRQ_SRAM_PARITY_ERR,
 * calls rom_trigger_unrecoverable(ROM_KM_UFAULT_SRAM_PARITY), which sends
 * RESP_UNRECOVERABLE_FAULT to the SEP mailbox and halts the CPU.
 */

#include "test_common.h"
#include "rom_defs.h"

#define SRAM_TEST_ADDR (SRAM_BASE + 0x100u)

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
        uint32_t expected = (uint32_t)(int32_t)ROM_KM_UFAULT_SRAM_PARITY;
        if (fault_code != expected) {
            TEST_FAIL("Wrong fault code: expected SRAM_PARITY");
        }
        TEST_PASS();
        return 0;
    }

    if (!tb_set_timeout(500000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(0xFA12u, 5000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    if (!tb_set_unrecoverable_watch(1, 1000u)) {
        TEST_FAIL("Failed to arm unrecoverable watcher");
    }

    rom_boot_init();

    /*
     * Prime SRAM with a known word and then force bad read parity. The
     * sticky IRQ should fire and the ISR should enter the unrecoverable path.
     */
    *(volatile uint32_t *)SRAM_TEST_ADDR = 0xC0FFEE01u;

    if (!tb_sram_parity_inject_enable()) {
        TEST_FAIL("Failed to enable SRAM parity injection");
    }

    volatile uint32_t x = *(volatile uint32_t *)SRAM_TEST_ADDR;
    (void)x;

    TEST_FAIL("CPU did not halt after SRAM parity error");
    return 0;
}
