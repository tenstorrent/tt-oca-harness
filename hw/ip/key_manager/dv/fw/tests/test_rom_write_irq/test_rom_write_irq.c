/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_rom_write_irq.c
 * @brief ROM write error interrupt test
 *
 * Verifies that ROM write attempts trigger the ROM write error interrupt:
 * 1. Enable ROM write interrupt
 * 2. Attempt to write to ROM (should trigger interrupt)
 * 3. Verify interrupt status bit is set
 * 4. Clear interrupt and verify it clears
 *
 * Run with:
 *   make run_fw FW_TEST=test_rom_write_irq
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "irq_common.h"
#include "rom_isr.h"
#include "rom_picorv32.h"

/* ROM address for test writes (ROM_BASE + ROM_TEST_OFFSET from test_common.h) */
#define ROM_TEST_ADDR (ROM_BASE + ROM_TEST_OFFSET)

/* ISR state */
static volatile uint32_t external_irq_count = 0;
static volatile uint32_t last_kmcsr_irq_status = 0;

/**
 * Custom ISR -- overrides weak rom_irq in crt0.s.
 * Captures KMCSR IRQ_STATUS for test verification and clears via W1C.
 */
void rom_irq(rom_irq_frame_t *frame) {
    uint32_t irq_mask = frame->irq_mask;

    /* Check if this is an external IRQ (KMCSR aggregated) */
    if (irq_mask & PICORV32_IRQ_KMCSR) {
        external_irq_count++;

        /* Read KMCSR IRQ_STATUS to identify the source */
        uint32_t current_status = rom_kmcsr_irq_status_read();
        TEST_LOG("  [ISR] KMCSR status=0x%08X", current_status);

        /* Record the status for test verification */
        last_kmcsr_irq_status = current_status;

        /* Always clear the interrupt to prevent retrigger */
        if (current_status != 0) {
            rom_kmcsr_irq_status_clear(current_status);
        }
    }
}

/**
 * Attempt to write to ROM address.
 * Uses volatile to ensure the write isn't optimized away.
 * -Warray-bounds is suppressed: addr is a hardware address, not an array index.
 */
static inline void write_rom(uint32_t addr, uint32_t data) {
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)addr;
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Warray-bounds"
    *p = data;
#pragma GCC diagnostic pop
}

/**
 * Read IRQ_STATUS register.
 */
static inline uint32_t read_irq_status(void) {
    return KMCSR_IRQ_STATUS_REG.w;
}

/**
 * Clear ROM write error IRQ_STATUS by writing 1 to sticky bit.
 */
static inline void clear_rom_write_irq_status(void) {
    km_csr__irq_status_reg_t clear_val = {0};
    clear_val.f.rom_write_err = 1;
    KMCSR_IRQ_STATUS_REG.w = clear_val.w;
}

/**
 * Enable ROM write interrupt.
 */
static inline void enable_rom_write_irq(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.rom_write_en = 1;
    KMCSR_IRQ_ENABLE_REG.w = enable.w;
}

int main(void) {
    uint32_t irq_status;

    TEST_INIT();

    /* Set timeout */
    if (!tb_set_timeout(100000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("ROM Write Interrupt Test\n");
    printf("========================\n\n");

    /* Enable CPU interrupts */
    printf("Enabling CPU interrupts (maskirq 0)...\n");
    uint32_t old_mask = rom_picorv32_maskirq(0);
    printf("Previous CPU IRQ mask: 0x%08X\n\n", old_mask);

    /* Test 1: Enable ROM write interrupt and attempt write */
    TEST_SUBTEST_START("ROM write interrupt triggered on write attempt");
    {
        /* Reset ISR state */
        external_irq_count = 0;
        last_kmcsr_irq_status = 0;

        /* Clear any previous ROM write errors */
        clear_rom_write_irq_status();
        test_delay(10);

        /* Enable ROM write interrupt */
        enable_rom_write_irq();
        TEST_LOG("  Enabled ROM write interrupt");

        /* Memory barrier to ensure enable is visible */
        __asm__ volatile("fence" ::: "memory");

        /* Attempt to write to ROM - this should trigger the interrupt */
        TEST_LOG("  Attempting write to ROM address 0x%08X...", ROM_TEST_ADDR);
        write_rom(ROM_TEST_ADDR, 0xDEADBEEF);

        /* Memory barrier and delay to ensure IRQ is processed */
        __asm__ volatile("fence" ::: "memory");
        test_delay(100); /* Give ISR time to execute */

        /* Verify ISR was called */
        if (external_irq_count == 0) {
            TEST_FAIL("ROM write IRQ did not trigger ISR (count=%d)", external_irq_count);
        }
        TEST_LOG("  ISR was called %d time(s)", external_irq_count);

        /* Verify correct IRQ source was identified (check the status captured in ISR) */
        {
            km_csr__irq_status_reg_t isr_status = {.w = last_kmcsr_irq_status};
            if (!isr_status.f.rom_write_err) {
                TEST_FAIL("IRQ_STATUS did not show ROM write bit (status=0x%08X)",
                          last_kmcsr_irq_status);
            }
        }
        TEST_LOG("  ROM write error bit correctly set in ISR (status=0x%08X)",
                 last_kmcsr_irq_status);

        /* Verify interrupt was cleared by ISR */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS after ISR clear: 0x%08X", irq_status);
        if (KMCSR_IRQ_STATUS_REG.f.rom_write_err) {
            TEST_FAIL("ROM write IRQ not cleared by ISR (status=0x%08X)", irq_status);
        }
        TEST_LOG("  ROM write error bit correctly cleared by ISR");
    }
    TEST_SUBTEST_PASS();

    /* Test 2: Verify interrupt is not triggered when disabled */
    TEST_SUBTEST_START("ROM write interrupt masked when disabled");
    {
        /* Reset ISR state */
        external_irq_count = 0;
        last_kmcsr_irq_status = 0;

        /* Disable ROM write interrupt */
        KMCSR_IRQ_ENABLE_REG.w = 0;
        TEST_LOG("  Disabled ROM write interrupt");

        /* Clear any previous errors */
        clear_rom_write_irq_status();
        test_delay(10);

        /* Memory barrier to ensure disable is visible */
        __asm__ volatile("fence" ::: "memory");

        /* Attempt to write to ROM again */
        TEST_LOG("  Attempting write to ROM with interrupt disabled...");
        write_rom(ROM_TEST_ADDR, 0xCAFEBABE);

        /* Memory barrier and delay */
        __asm__ volatile("fence" ::: "memory");
        test_delay(100);

        /* Verify ISR was NOT called (interrupt is masked) */
        if (external_irq_count != 0) {
            TEST_FAIL("ISR was called when interrupt was disabled (count=%d)", external_irq_count);
        }
        TEST_LOG("  ISR was not called (correctly masked)");

        /* However, the status bit should still be set (error detected, just not interrupting) */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS: 0x%08X", irq_status);

        if (!KMCSR_IRQ_STATUS_REG.f.rom_write_err) {
            TEST_FAIL("IRQ_STATUS should show ROM write bit even when masked (status=0x%08X)",
                      irq_status);
        }
        TEST_LOG("  ROM write error bit still set (correct - error detected, interrupt masked)");
    }
    TEST_SUBTEST_PASS();

    /* Test 3: Verify W1C clear functionality */
    TEST_SUBTEST_START("ROM write interrupt W1C clear functionality");
    {
        /* Snapshot the ISR count; it must not change while the interrupt is disabled */
        uint32_t irq_count_before = external_irq_count;

        /* Disable the interrupt so the ISR does not run; the W1C clear below is done by hand */
        KMCSR_IRQ_ENABLE_REG.w = 0;
        TEST_LOG("  Disabled ROM write interrupt for manual W1C test");
        __asm__ volatile("fence" ::: "memory");
        test_delay(10);

        /* Clear any previous status */
        clear_rom_write_irq_status();
        test_delay(10);

        /* Trigger write error - status will be set, but ISR won't run */
        TEST_LOG("  Triggering ROM write error with interrupt disabled...");
        write_rom(ROM_TEST_ADDR, 0x87654321);
        __asm__ volatile("fence" ::: "memory");
        test_delay(10);

        /* Verify status bit is set */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS before manual W1C clear: 0x%08X", irq_status);
        if (!KMCSR_IRQ_STATUS_REG.f.rom_write_err) {
            TEST_FAIL("ROM write error bit not set (status=0x%08X)", irq_status);
        }

        /* Verify ISR was NOT called (interrupt disabled) - count should not increase */
        if (external_irq_count != irq_count_before) {
            TEST_FAIL(
                "ISR should not be called when interrupt is disabled (count before=%d, after=%d)",
                irq_count_before, external_irq_count);
        }

        /* Clear the interrupt by writing 1 to the sticky bit (W1C) */
        TEST_LOG("  Clearing ROM write error interrupt via W1C...");
        clear_rom_write_irq_status();
        test_delay(10); /* Wait for clear to propagate */

        /* Verify clear took effect */
        irq_status = read_irq_status();
        TEST_LOG("  IRQ_STATUS after W1C clear: 0x%08X", irq_status);
        if (KMCSR_IRQ_STATUS_REG.f.rom_write_err) {
            TEST_FAIL("ROM write IRQ not cleared after W1C (status=0x%08X)", irq_status);
        }
        TEST_LOG("  ROM write error bit correctly cleared via W1C");
    }
    TEST_SUBTEST_PASS();

    printf("\nAll ROM write interrupt tests passed!\n");

    /* Restore IRQ mask */
    rom_picorv32_maskirq(old_mask);
    TEST_PASS();
    return 0;
}
