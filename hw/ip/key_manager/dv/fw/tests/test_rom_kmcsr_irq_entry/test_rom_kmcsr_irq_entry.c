/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_kmcsr_irq_entry.c
 * @brief Exercises `rom_kmcsr_irq_entry_*` drivers for IRQ_ENTRY_ADDR / IRQ_ENTRY_LOCK.
 *
 * Run: `make run_fw FW_TEST=test_rom_kmcsr_irq_entry`
 */

#include "test_common.h"
#include "rom_kmcsr.h"

/**
 * @brief Verify IRQ entry KMCSR drivers against reset, lock, and SW-wel behavior.
 *
 * @return Does not return; halts via TEST_PASS or TEST_FAIL.
 */
int main(void) {
    TEST_INIT();

    TEST_SUBTEST_START("Reset readback via rom_kmcsr_irq_entry_*");
    TEST_ASSERT_EQ(rom_kmcsr_irq_entry_addr_read(), KM_CSR__IRQ_ENTRY_ADDR_REG__ADDR_reset,
                   "IRQ_ENTRY_ADDR reset");
    TEST_ASSERT_EQ((uint32_t)rom_kmcsr_irq_entry_lock_read(), 0u, "IRQ_ENTRY_LOCK reset");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Addr write and read while unlocked");
    rom_kmcsr_irq_entry_addr_write(0x00000200u);
    TEST_ASSERT_EQ(rom_kmcsr_irq_entry_addr_read(), 0x200u, "IRQ_ENTRY_ADDR after write");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Lock set and addr writes ignored");
    rom_kmcsr_irq_entry_lock_set();
    TEST_ASSERT_EQ((uint32_t)rom_kmcsr_irq_entry_lock_read(), 1u, "lock after set");
    rom_kmcsr_irq_entry_addr_write(0x00000300u);
    TEST_ASSERT_EQ(rom_kmcsr_irq_entry_addr_read(), 0x200u, "IRQ_ENTRY_ADDR unchanged when locked");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Writing 0 to LOCK does not clear (hardware)");
    {
        km_csr__irq_entry_lock_reg_t z = {0};
        ROM_KMCSR_IRQ_ENTRY_LOCK_REG.w = z.w;
    }
    TEST_ASSERT_EQ((uint32_t)rom_kmcsr_irq_entry_lock_read(), 1u, "lock after W0");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
