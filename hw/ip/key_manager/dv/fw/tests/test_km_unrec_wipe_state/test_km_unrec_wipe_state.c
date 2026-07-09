/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_wipe_state.c
 * @brief Unrecoverable fault test: WIPE_STATE
 *
 * Triggers the wipe_state input via the testbench, which fires the KMCSR
 * wipe IRQ. The production ISR path (rom_trigger_unrecoverable) purges crypto
 * engine keys, sends RESP_UNRECOVERABLE_FAULT to the SEP mailbox, shreds
 * all SRAM with pseudorandom data, and halts the CPU via ebreak.
 *
 * Because the CPU halts after wipe, the firmware cannot verify the result
 * directly. The cocotb testbench reads the SEP mailbox and checks for
 * the expected fault message. If the wipe handler fails to execute, the
 * firmware falls through to TEST_FAIL.
 */

#include "test_common.h"
#include "rom_defs.h"

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 1;
}

int main(void) {
    TEST_INIT();

    if (tb_check_unrecoverable_restart(1000)) {
        uint32_t fault_code;
        if (!tb_get_unrecoverable_fault_code(1000, &fault_code)) {
            TEST_FAIL("Failed to get unrecoverable fault code");
        }
        uint32_t expected = (uint32_t)(int32_t)ROM_KM_UFAULT_WIPE_STATE;
        if (fault_code != expected) {
            TEST_FAIL("Wrong fault code: expected WIPE_STATE");
        }
        TEST_PASS();
        return 0;
    }

    if (!tb_set_timeout(1500000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(0xD1E5u, 5000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    if (!tb_set_unrecoverable_watch(1, 1000u)) {
        TEST_FAIL("Failed to arm unrecoverable watcher");
    }

    rom_boot_init();

    tb_wipe_trigger(5000);

    TEST_FAIL("CPU did not halt after wipe");
    return 0;
}
