/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_irq_entry_program.c
 * @brief Program IRQ_ENTRY_ADDR while unlocked; misaligned readback; interrupt uses last/alternate
 * entry.
 */

#include "test_common.h"
#include "rom_isr.h"

volatile uint32_t irq_entry_alt_hit;
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
 * @brief Program IRQ_ENTRY_ADDR and confirm interrupt uses alternate VROM entry.
 *
 * @return Does not return; halts via TEST_PASS or TEST_FAIL.
 */
int main(void) {
    TEST_INIT();

    TEST_SUBTEST_START("Multiple writes and misaligned readback while unlocked");
    irq_entry_addr_write(0x200u);
    if (irq_entry_addr_read() != 0x200u) {
        TEST_FAIL("addr after 0x200: got 0x%08X", irq_entry_addr_read());
    }
    irq_entry_addr_write(0x10000103u); /* misaligned PC; stored verbatim */
    if (irq_entry_addr_read() != 0x10000103u) {
        TEST_FAIL("addr after misaligned write: got 0x%08X", irq_entry_addr_read());
    }
    irq_entry_addr_write(IRQ_ENTRY_ALT_VROM_PC);
    if (irq_entry_addr_read() != IRQ_ENTRY_ALT_VROM_PC) {
        TEST_FAIL("addr before IRQ: got 0x%08X", irq_entry_addr_read());
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Interrupt enters alternate VROM stub");
    irq_entry_alt_hit = 0;
    kmcsr_irq_hits = 0;
    irq_entry_fire_kmcsr_rom_parity();
    if (kmcsr_irq_hits == 0u) {
        TEST_FAIL("KMCSR IRQ handler not reached (hits=%u)", kmcsr_irq_hits);
    }
    if (irq_entry_alt_hit == 0u) {
        TEST_FAIL("Alternate entry stub did not run (alt_hit=%u)", irq_entry_alt_hit);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
