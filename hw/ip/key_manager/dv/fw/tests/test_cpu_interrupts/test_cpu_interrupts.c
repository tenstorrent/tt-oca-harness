/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_cpu_interrupts.c
 * @brief CPU Interrupt Test - Tests PicoRV32 internal interrupt sources
 *
 * This test verifies the two internal interrupt sources available with
 * the current PicoRV32 configuration (ENABLE_IRQ_TIMER=0):
 *
 *   IRQ 1 - EBREAK/ECALL/Illegal Instruction
 *   IRQ 2 - Bus Error (Misaligned Memory Access)
 *
 * Test Strategy:
 *   1. Enable interrupts via maskirq instruction
 *   2. Trigger EBREAK, verify IRQ 1 handler is called
 *   3. Trigger misaligned load, verify IRQ 2 handler is called
 *   4. Verify handler can modify return address to skip faulting instruction
 */

#include "test_common.h"
#include "rom_isr.h"
#include "rom_picorv32.h"
#include <stdint.h>

/*===========================================================================
 * IRQ Handler State
 *===========================================================================*/

/* Counters for each IRQ source */
volatile uint32_t irq1_count = 0; /* EBREAK/Illegal instruction */
volatile uint32_t irq2_count = 0; /* Bus error */

/* Last IRQ bitmask received */
volatile uint32_t last_irq_mask = 0;

/* Flag to indicate whether to skip the faulting instruction */
volatile int skip_faulting_insn = 0;

/*===========================================================================
 * C IRQ Handler (called from assembly irq_handler)
 *===========================================================================*/

/**
 * IRQ handler called from crt0.s (overrides weak rom_irq).
 * @param frame Pointer to saved IRQ frame.
 */
void rom_irq(rom_irq_frame_t *frame) {
    uint32_t irq_mask = frame->irq_mask;
    last_irq_mask = irq_mask;

    /* IRQ 1: EBREAK or Illegal Instruction */
    if (irq_mask & (1u << 1)) {
        irq1_count++;
        printf("  IRQ1: EBREAK/Illegal @ PC=0x%08X\n", frame->ret_addr);

        if (skip_faulting_insn) {
            /*
             * Skip the faulting instruction.
             * PicoRV32 sets the LSB of ret_addr when the C extension is
             * enabled and the previous instruction was compressed (2-byte).
             * Clear the LSB to get the true return PC; the CPU already
             * advanced past the faulting instruction in both the
             * compressed and 32-bit cases, so a single clear suffices.
             */
            uint32_t pc = frame->ret_addr & ~1u;
            frame->ret_addr = pc;
        }
    }

    /* IRQ 2: Bus Error (misaligned access) */
    if (irq_mask & (1u << 2)) {
        irq2_count++;
        printf("  IRQ2: Bus Error @ PC=0x%08X\n", frame->ret_addr);

        if (skip_faulting_insn) {
            /* Clear LSB and use the already-advanced return PC. */
            uint32_t pc = frame->ret_addr & ~1u;
            frame->ret_addr = pc;
        }
    }
}

/*===========================================================================
 * Test Functions
 *===========================================================================*/

/**
 * Test IRQ 1 by executing EBREAK instruction.
 */
static int test_ebreak_irq(void) {
    TEST_SUBTEST_START("EBREAK Interrupt (IRQ 1)");

    /* Reset counters */
    irq1_count = 0;
    last_irq_mask = 0;
    skip_faulting_insn = 1; /* Skip EBREAK so we can continue */

    printf("  Executing EBREAK instruction...\n");

    /* Execute EBREAK - this should trigger IRQ 1 */
    __asm__ volatile("ebreak");

    /* Check that IRQ 1 was triggered */
    if (irq1_count == 0) {
        TEST_FAIL("EBREAK did not trigger IRQ 1 (irq1_count=%d)", irq1_count);
    }

    if (!(last_irq_mask & (1 << 1))) {
        TEST_FAIL("IRQ mask did not have bit 1 set (mask=0x%08X)", last_irq_mask);
    }

    printf("  EBREAK triggered IRQ 1 successfully (count=%d)\n", irq1_count);
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test IRQ 2 by performing misaligned memory access.
 */
static int test_misaligned_irq(void) {
    TEST_SUBTEST_START("Misaligned Access Interrupt (IRQ 2)");

    /* Reset counters */
    irq2_count = 0;
    last_irq_mask = 0;
    skip_faulting_insn = 1; /* Skip faulting instruction */

    printf("  Performing misaligned word load...\n");

    /*
     * Perform a misaligned 32-bit load.
     * Address 0x2001 is not word-aligned (not divisible by 4).
     * This should trigger IRQ 2 (bus error).
     *
     * We use inline assembly to ensure the compiler doesn't optimize this out.
     */
    volatile uint32_t result = 0;
    __asm__ volatile("li t0, 0x2001\n" /* Load misaligned address */
                     "lw %0, 0(t0)\n"  /* Attempt misaligned load */
                     : "=r"(result)
                     :
                     : "t0");

    /* The load might not complete due to trap, result may be garbage */
    (void)result;

    /* Check that IRQ 2 was triggered */
    if (irq2_count == 0) {
        TEST_FAIL("Misaligned access did not trigger IRQ 2 (irq2_count=%d)", irq2_count);
    }

    if (!(last_irq_mask & (1 << 2))) {
        TEST_FAIL("IRQ mask did not have bit 2 set (mask=0x%08X)", last_irq_mask);
    }

    printf("  Misaligned access triggered IRQ 2 successfully (count=%d)\n", irq2_count);
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test that interrupts can be masked.
 */
static int test_irq_masking(void) {
    TEST_SUBTEST_START("IRQ Masking");

    uint32_t old_mask;

    /* First, mask all interrupts */
    printf("  Masking all IRQs...\n");
    old_mask = rom_picorv32_maskirq(0xFFFFFFFF);
    printf("  Previous mask was 0x%08X\n", old_mask);

    /* Reset counter */
    irq1_count = 0;

    /*
     * NOTE: We cannot test EBREAK with IRQs masked because PicoRV32
     * will HALT if EBREAK occurs while IRQ 1 is masked!
     * So we just verify the maskirq instruction works.
     */

    /* Re-enable all IRQs */
    printf("  Re-enabling all IRQs...\n");
    old_mask = rom_picorv32_maskirq(0x00000000);

    if (old_mask != 0xFFFFFFFF) {
        TEST_FAIL("maskirq did not return expected mask (got 0x%08X, expected 0xFFFFFFFF)",
                  old_mask);
    }

    printf("  IRQ masking works correctly\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test multiple sequential interrupts.
 */
static int test_multiple_interrupts(void) {
    TEST_SUBTEST_START("Multiple Sequential Interrupts");

    /* Reset counters */
    irq1_count = 0;
    irq2_count = 0;
    skip_faulting_insn = 1;

    printf("  Triggering EBREAK...\n");
    __asm__ volatile("ebreak");

    printf("  Triggering misaligned access...\n");
    volatile uint32_t result = 0;
    __asm__ volatile("li t0, 0x2003\n"
                     "lw %0, 0(t0)\n"
                     : "=r"(result)
                     :
                     : "t0");
    (void)result;

    printf("  Triggering another EBREAK...\n");
    __asm__ volatile("ebreak");

    /* Verify counts */
    if (irq1_count != 2) {
        TEST_FAIL("Expected 2 EBREAK IRQs, got %d", irq1_count);
    }

    if (irq2_count != 1) {
        TEST_FAIL("Expected 1 bus error IRQ, got %d", irq2_count);
    }

    printf("  All interrupts handled correctly (IRQ1=%d, IRQ2=%d)\n", irq1_count, irq2_count);
    TEST_SUBTEST_PASS();
    return 0;
}

/*===========================================================================
 * Main Test Entry Point
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    printf("CPU Interrupt Test\n");
    printf("==================\n");
    printf("Testing PicoRV32 internal interrupt sources:\n");
    printf("  IRQ 1: EBREAK/Illegal Instruction\n");
    printf("  IRQ 2: Bus Error (Misaligned Access)\n\n");

    /* Enable all interrupts (mask = 0 means all enabled) */
    printf("Enabling interrupts (maskirq 0)...\n");
    uint32_t old_mask = rom_picorv32_maskirq(0x00000000);
    printf("Previous IRQ mask: 0x%08X\n\n", old_mask);

    /* Run tests */
    test_ebreak_irq();
    test_misaligned_irq();
    test_irq_masking();
    test_multiple_interrupts();

    /* All tests passed */
    printf("\nAll interrupt tests passed!\n");
    TEST_PASS();

    return 0;
}
