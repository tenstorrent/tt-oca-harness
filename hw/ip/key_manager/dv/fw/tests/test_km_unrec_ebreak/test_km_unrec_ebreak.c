/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_unrec_ebreak.c
 * @brief Unrecoverable fault test: EBREAK
 *
 * Executes an EBREAK instruction, which triggers PicoRV32 IRQ bit 1
 * (EBREAK/illegal). The ISR detects that the faulting instruction is
 * a genuine ebreak and calls rom_trigger_unrecoverable(ROM_KM_UFAULT_EBREAK),
 * which sends RESP_UNRECOVERABLE_FAULT to the SEP mailbox and halts
 * via ebreak. PicoRV32 enters hardware trap state (irq_active prevents
 * ISR re-entry), asserting unrecoverable_err_o.
 *
 * The testbench watches unrecoverable_err and resets the DUT. On
 * restart the firmware detects the prior reset via
 * TB_CMD_CHECK_UNRECOVERABLE_RESTART and passes immediately.
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
        uint32_t expected = (uint32_t)(int32_t)ROM_KM_UFAULT_EBREAK;
        if (fault_code != expected) {
            TEST_FAIL("Wrong fault code: expected EBREAK");
        }
        TEST_PASS();
        return 0;
    }

    if (!tb_set_timeout(500000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    if (!tb_drbg_set_seed(0xBAADu, 5000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    if (!tb_set_unrecoverable_watch(1, 1000u)) {
        TEST_FAIL("Failed to arm unrecoverable watcher");
    }

    rom_boot_init();

    __asm__ volatile("ebreak");

    TEST_FAIL("CPU did not halt after ebreak");
    return 0;
}
