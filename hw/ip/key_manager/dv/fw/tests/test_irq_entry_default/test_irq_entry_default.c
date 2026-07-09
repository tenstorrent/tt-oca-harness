/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_irq_entry_default.c
 * @brief Default IRQ-entry path: reset CSR values and interrupt without programming IRQ_ENTRY_*.
 */

#include "test_common.h"
#include "rom_isr.h"

static volatile uint32_t kmcsr_irq_hits;

/**
 * @brief Handle PicoRV32 interrupts; counts KMCSR IRQs and clears IRQ status.
 *
 * @param frame IRQ frame supplied by the ISR trampoline.
 */
void rom_irq(rom_irq_frame_t *frame) {
    if (frame->irq_mask & PICORV32_IRQ_KMCSR) {
        kmcsr_irq_hits++;
        rom_kmcsr_irq_status_clear(irq_entry_test_all_status_mask());
    }
}

/**
 * @brief Verify reset values and default IRQ entry without programming IRQ_ENTRY_*.
 *
 * @return Does not return; halts via TEST_PASS or TEST_FAIL.
 */
int main(void) {
    TEST_INIT();

    TEST_SUBTEST_START("IRQ_ENTRY reset readback");
    if (irq_entry_addr_read() != 0x10u) {
        TEST_FAIL("IRQ_ENTRY_ADDR reset expected 0x10, got 0x%08X", irq_entry_addr_read());
    }
    if (irq_entry_lock_read() != 0u) {
        TEST_FAIL("IRQ_ENTRY_LOCK reset expected 0, got %u", irq_entry_lock_read());
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Default IRQ entry with unprogrammed CSR");
    kmcsr_irq_hits = 0;
    irq_entry_fire_kmcsr_rom_parity();
    if (kmcsr_irq_hits == 0u) {
        TEST_FAIL("KMCSR IRQ did not run (hits=%u)", kmcsr_irq_hits);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
