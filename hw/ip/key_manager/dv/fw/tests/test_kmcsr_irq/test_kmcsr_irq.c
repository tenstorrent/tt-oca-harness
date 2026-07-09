/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kmcsr_irq.c
 * @brief Test software-triggered interrupts via KMCSR IRQ_SET register
 *
 * This test exercises the KMCSR interrupt registers:
 * - IRQ_STATUS: Read interrupt status, W1C to clear sticky bits
 * - IRQ_ENABLE: Enable/disable individual interrupt sources
 * - IRQ_SET: Software trigger for interrupt testing
 *
 * Tests verify that writing to IRQ_SET triggers the ISR and that
 * the correct status bits are reported.
 */

#include "test_common.h"
#include "irq_common.h"
#include "rom_isr.h"
#include "rom_picorv32.h"

/* Helper to construct IRQ enable/clear mask from struct fields (all software-triggerable sources)
 */
static inline uint32_t irq_all_sources_mask(void) {
    km_csr__irq_status_reg_t mask = {0};
    mask.f.rom_parity_err = 1;
    mask.f.sram_parity_err = 1;
    mask.f.rom_write_err = 1;
    mask.f.sram_write_lock_err = 1;
    mask.f.axi_slverr = 1;
    mask.f.axi_decerr = 1;
    mask.f.drbg_err = 1;
    mask.f.wipe_state = 1;
    return mask.w;
}

/* Helper to construct IRQ enable value for ROM parity */
static inline uint32_t irq_rom_parity_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.rom_parity_en = 1;
    return enable.w;
}

/* Helper to construct IRQ enable value for SRAM parity */
static inline uint32_t irq_sram_parity_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.sram_parity_en = 1;
    return enable.w;
}

/* Helper to construct IRQ enable value for ROM write */
static inline uint32_t irq_rom_write_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.rom_write_en = 1;
    return enable.w;
}

/* Helper to construct IRQ enable value for SRAM write-lock */
static inline uint32_t irq_sram_write_lock_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.sram_write_lock_en = 1;
    return enable.w;
}

/* Helper to construct IRQ enable value for AXI SLVERR */
static inline uint32_t irq_axi_slverr_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.axi_slverr_en = 1;
    return enable.w;
}

/* Helper to construct IRQ enable value for AXI DECERR */
static inline uint32_t irq_axi_decerr_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.axi_decerr_en = 1;
    return enable.w;
}

/* Helper to construct IRQ_SET value for ROM write */
static inline uint32_t irq_set_rom_write(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.rom_write_err_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ_SET value for SRAM write-lock */
static inline uint32_t irq_set_sram_write_lock(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.sram_write_lock_err_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ_SET value for ROM parity */
static inline uint32_t irq_set_rom_parity(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.rom_parity_err_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ_SET value for SRAM parity */
static inline uint32_t irq_set_sram_parity(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.sram_parity_err_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ_SET value for AXI SLVERR */
static inline uint32_t irq_set_axi_slverr(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.axi_slverr_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ_SET value for AXI DECERR */
static inline uint32_t irq_set_axi_decerr(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.axi_decerr_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ enable value for DRBG error */
static inline uint32_t irq_drbg_err_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.drbg_err_en = 1;
    return enable.w;
}

/* Helper to construct IRQ enable value for wipe state */
static inline uint32_t irq_wipe_state_enable(void) {
    km_csr__irq_enable_reg_t enable = {0};
    enable.f.wipe_state_en = 1;
    return enable.w;
}

/* Helper to construct IRQ_SET value for DRBG error */
static inline uint32_t irq_set_drbg_err(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.drbg_err_set = 1;
    return set_val.w;
}

/* Helper to construct IRQ_SET value for wipe state */
static inline uint32_t irq_set_wipe_state(void) {
    km_csr__irq_set_reg_t set_val = {0};
    set_val.f.wipe_state_set = 1;
    return set_val.w;
}

/*===========================================================================
 * Test State
 *===========================================================================*/

/* ISR counters and state */
static volatile uint32_t external_irq_count = 0;
static volatile uint32_t last_kmcsr_irq_status = 0;
static volatile uint32_t last_picorv32_irq_mask = 0;

/* Control flags */
static volatile int clear_irq_in_handler = 1;

/*===========================================================================
 * IRQ Handler
 *===========================================================================*/

/**
 * IRQ handler called from crt0.s (overrides weak rom_irq).
 * @param frame Pointer to saved IRQ frame.
 */
void rom_irq(rom_irq_frame_t *frame) {
    uint32_t irq_mask = frame->irq_mask;
    last_picorv32_irq_mask = irq_mask;

    /* Check if this is an external IRQ (KMCSR aggregated) */
    if (irq_mask & PICORV32_IRQ_KMCSR) {
        external_irq_count++;

        /* Read KMCSR IRQ_STATUS to identify the source */
        uint32_t current_status = rom_kmcsr_irq_status_read();

        /* Debug: print status to see what we got */
        printf("  [ISR] KMCSR status=0x%08X\n", current_status);

        /* Record the status for test verification */
        last_kmcsr_irq_status = current_status;

        /* Clear the interrupt if requested and there are bits to clear */
        if (clear_irq_in_handler && current_status != 0) {
            rom_kmcsr_irq_status_clear(current_status);
        }
    }

    /* Handle internal IRQs if any (EBREAK, Bus Error) */
    if (irq_mask & PICORV32_IRQ_EBREAK) {
        printf("  [IRQ] EBREAK/Illegal @ PC=0x%08X\n", frame->ret_addr);
    }
    if (irq_mask & PICORV32_IRQ_BUSERR) {
        printf("  [IRQ] Bus Error @ PC=0x%08X\n", frame->ret_addr);
    }
}

/*===========================================================================
 * Test Functions
 *===========================================================================*/

/**
 * Test 1: Software-triggered ROM parity error interrupt
 */
static int test_sw_rom_parity_irq(void) {
    TEST_SUBTEST_START("Software-triggered ROM parity IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable ROM parity IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_rom_parity_enable());

    printf("  Triggering ROM parity IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_rom_parity());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("ROM parity IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.rom_parity_err) {
            TEST_FAIL("IRQ_STATUS did not show ROM parity bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.rom_parity_err) {
        TEST_FAIL("ROM parity IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  ROM parity IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 2: Software-triggered SRAM parity error interrupt
 */
static int test_sw_sram_parity_irq(void) {
    TEST_SUBTEST_START("Software-triggered SRAM parity IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable SRAM parity IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_sram_parity_enable());

    printf("  Triggering SRAM parity IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_sram_parity());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("SRAM parity IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.sram_parity_err) {
            TEST_FAIL("IRQ_STATUS did not show SRAM parity bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.sram_parity_err) {
        TEST_FAIL("SRAM parity IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  SRAM parity IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 3: Software-triggered ROM write error interrupt
 */
static int test_sw_rom_write_irq(void) {
    TEST_SUBTEST_START("Software-triggered ROM write IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable ROM write IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_rom_write_enable());

    printf("  Triggering ROM write IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_rom_write());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("ROM write IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.rom_write_err) {
            TEST_FAIL("IRQ_STATUS did not show ROM write bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.rom_write_err) {
        TEST_FAIL("ROM write IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  ROM write IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test: Software-triggered SRAM write-lock interrupt
 */
static int test_sw_sram_write_lock_irq(void) {
    TEST_SUBTEST_START("Software-triggered SRAM write-lock IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable SRAM write-lock IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_sram_write_lock_enable());

    printf("  Triggering SRAM write-lock IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_sram_write_lock());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("SRAM write-lock IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.sram_write_lock_err) {
            TEST_FAIL("IRQ_STATUS did not show SRAM write-lock bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.sram_write_lock_err) {
        TEST_FAIL("SRAM write-lock IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  SRAM write-lock IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test: Multiple IRQ sources simultaneously
 */
static int test_multiple_irq_sources(void) {
    TEST_SUBTEST_START("Multiple IRQ sources");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable both parity IRQs */
    {
        km_csr__irq_enable_reg_t enable = {0};
        enable.f.rom_parity_en = 1;
        enable.f.sram_parity_en = 1;
        rom_kmcsr_irq_enable_write(enable.w);
    }

    printf("  Triggering both parity IRQs via IRQ_SET...\n");

    /* Trigger both interrupts via software */
    {
        km_csr__irq_set_reg_t set_val = {0};
        set_val.f.rom_parity_err_set = 1;
        set_val.f.sram_parity_err_set = 1;
        rom_kmcsr_irq_set(set_val.w);
    }

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("Multiple IRQs did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify both IRQ sources were identified */
    km_csr__irq_status_reg_t expected_reg = {0};
    expected_reg.f.rom_parity_err = 1;
    expected_reg.f.sram_parity_err = 1;
    uint32_t expected = expected_reg.w;
    if ((last_kmcsr_irq_status & expected) != expected) {
        TEST_FAIL("IRQ_STATUS missing bits (status=0x%08X, expected=0x%08X)", last_kmcsr_irq_status,
                  expected);
    }

    /* Verify IRQs were cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (status_after & expected) {
        TEST_FAIL("IRQs not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  Multiple IRQs triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 4: IRQ masking (disabled IRQ should not trigger ISR)
 */
static int test_irq_masking(void) {
    TEST_SUBTEST_START("IRQ masking");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 0; /* Don't clear in handler for this test */

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Disable all IRQs in KMCSR */
    rom_kmcsr_irq_enable_write(0);

    printf("  Triggering ROM parity IRQ with IRQ disabled...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_rom_parity());

    /* Memory barrier and small delay */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was NOT called (IRQ was masked) */
    if (external_irq_count != 0) {
        TEST_FAIL("Masked IRQ triggered ISR (count=%d)", external_irq_count);
    }

    /* Verify IRQ_STATUS still shows the pending IRQ */
    uint32_t status = rom_kmcsr_irq_status_read();
    if (!KMCSR_IRQ_STATUS_REG.f.rom_parity_err) {
        TEST_FAIL("IRQ_STATUS should show pending IRQ (status=0x%08X)", status);
    }

    printf("  Masked IRQ correctly did not trigger ISR\n");

    /* Now enable the IRQ and verify it triggers */
    printf("  Enabling IRQ...\n");
    clear_irq_in_handler = 1;
    rom_kmcsr_irq_enable_write(irq_rom_parity_enable());

    /* Small delay for IRQ to trigger */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called after enabling */
    if (external_irq_count == 0) {
        TEST_FAIL("IRQ did not trigger after enable (count=%d)", external_irq_count);
    }

    printf("  IRQ triggered after enable\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 5: IRQ enable toggle
 */
static int test_irq_enable_toggle(void) {
    TEST_SUBTEST_START("IRQ enable toggle");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable ROM parity IRQ */
    rom_kmcsr_irq_enable_write(irq_rom_parity_enable());

    /* Read back and verify */
    uint32_t enable = rom_kmcsr_irq_enable_read();
    if (!KMCSR_IRQ_ENABLE_REG.f.rom_parity_en) {
        TEST_FAIL("IRQ_ENABLE readback mismatch (got=0x%08X, expected ROM parity enabled)", enable);
    }

    /* Disable all */
    rom_kmcsr_irq_enable_write(0);
    enable = rom_kmcsr_irq_enable_read();
    if (enable != 0) {
        TEST_FAIL("IRQ_ENABLE should be 0 (got=0x%08X)", enable);
    }

    /* Enable multiple */
    km_csr__irq_enable_reg_t enable_multi = {0};
    enable_multi.f.rom_parity_en = 1;
    enable_multi.f.sram_parity_en = 1;
    uint32_t multi = enable_multi.w;
    rom_kmcsr_irq_enable_write(multi);
    enable = rom_kmcsr_irq_enable_read();
    if (enable != multi) {
        TEST_FAIL("IRQ_ENABLE multi readback mismatch (got=0x%08X, expected=0x%08X)", enable,
                  multi);
    }

    printf("  IRQ enable toggle works correctly\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 7: Software-triggered AXI SLVERR error interrupt
 */
static int test_sw_axi_slverr_irq(void) {
    TEST_SUBTEST_START("Software-triggered AXI SLVERR IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable AXI SLVERR IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_axi_slverr_enable());

    printf("  Triggering AXI SLVERR IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_axi_slverr());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("AXI SLVERR IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.axi_slverr) {
            TEST_FAIL("IRQ_STATUS did not show AXI SLVERR bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.axi_slverr) {
        TEST_FAIL("AXI SLVERR IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  AXI SLVERR IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 8: Software-triggered AXI DECERR error interrupt
 */
static int test_sw_axi_decerr_irq(void) {
    TEST_SUBTEST_START("Software-triggered AXI DECERR IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable AXI DECERR IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_axi_decerr_enable());

    printf("  Triggering AXI DECERR IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_axi_decerr());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("AXI DECERR IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.axi_decerr) {
            TEST_FAIL("IRQ_STATUS did not show AXI DECERR bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.axi_decerr) {
        TEST_FAIL("AXI DECERR IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  AXI DECERR IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 9: Software-triggered DRBG Sampler error interrupt
 */
static int test_sw_drbg_err_irq(void) {
    TEST_SUBTEST_START("Software-triggered DRBG error IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable DRBG error IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_drbg_err_enable());

    printf("  Triggering DRBG error IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_drbg_err());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("DRBG error IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.drbg_err) {
            TEST_FAIL("IRQ_STATUS did not show DRBG error bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.drbg_err) {
        TEST_FAIL("DRBG error IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  DRBG error IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/**
 * Test 10: Software-triggered wipe state interrupt
 */
static int test_sw_wipe_state_irq(void) {
    TEST_SUBTEST_START("Software-triggered wipe state IRQ");

    /* Reset state */
    external_irq_count = 0;
    last_kmcsr_irq_status = 0;
    clear_irq_in_handler = 1;

    /* Clear any pending IRQs first */
    rom_kmcsr_irq_status_clear(irq_all_sources_mask());

    /* Enable wipe state IRQ in KMCSR */
    rom_kmcsr_irq_enable_write(irq_wipe_state_enable());

    printf("  Triggering wipe state IRQ via IRQ_SET...\n");

    /* Trigger the interrupt via software */
    rom_kmcsr_irq_set(irq_set_wipe_state());

    /* Memory barrier and small delay to ensure IRQ is processed */
    __asm__ volatile("fence" ::: "memory");
    for (volatile int i = 0; i < 100; i++) {
    }

    /* Verify ISR was called */
    if (external_irq_count == 0) {
        TEST_FAIL("Wipe state IRQ did not trigger ISR (count=%d)", external_irq_count);
    }

    /* Verify correct IRQ source was identified */
    {
        km_csr__irq_status_reg_t status_reg = {.w = last_kmcsr_irq_status};
        if (!status_reg.f.wipe_state) {
            TEST_FAIL("IRQ_STATUS did not show wipe state bit (status=0x%08X)",
                      last_kmcsr_irq_status);
        }
    }

    /* Verify IRQ was cleared */
    uint32_t status_after = rom_kmcsr_irq_status_read();
    if (KMCSR_IRQ_STATUS_REG.f.wipe_state) {
        TEST_FAIL("Wipe state IRQ not cleared after W1C (status=0x%08X)", status_after);
    }

    printf("  Wipe state IRQ triggered and cleared successfully\n");
    TEST_SUBTEST_PASS();
    return 0;
}

/*===========================================================================
 * Main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    /* Set timeout to accommodate all 11 interrupt tests (needs ~300k cycles) */
    if (!tb_set_timeout(300000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    printf("KMCSR Interrupt Test\n");
    printf("====================\n");
    printf("Testing software-triggered interrupts via IRQ_SET register\n\n");

    /* Enable CPU interrupts */
    printf("Enabling CPU interrupts (maskirq 0)...\n");
    uint32_t old_mask = rom_picorv32_maskirq(0);
    printf("Previous CPU IRQ mask: 0x%08X\n\n", old_mask);

    /* Run tests */
    /* Sticky IRQ source tests (sustained km_irq_o level — works with non-latched PicoRV32) */
    printf("[1] Software-triggered ROM parity IRQ...\n");
    if (test_sw_rom_parity_irq() != 0) goto fail;

    printf("\n[2] Software-triggered SRAM parity IRQ...\n");
    if (test_sw_sram_parity_irq() != 0) goto fail;

    printf("\n[3] Software-triggered ROM write IRQ...\n");
    if (test_sw_rom_write_irq() != 0) goto fail;

    printf("\n[4] Software-triggered SRAM write-lock IRQ...\n");
    if (test_sw_sram_write_lock_irq() != 0) goto fail;

    printf("\n[5] Software-triggered AXI SLVERR IRQ...\n");
    if (test_sw_axi_slverr_irq() != 0) goto fail;

    printf("\n[6] Software-triggered AXI DECERR IRQ...\n");
    if (test_sw_axi_decerr_irq() != 0) goto fail;

    printf("\n[7] Software-triggered DRBG error IRQ...\n");
    if (test_sw_drbg_err_irq() != 0) goto fail;

    printf("\n[8] Software-triggered wipe state IRQ...\n");
    if (test_sw_wipe_state_irq() != 0) goto fail;

    /* Multiple interrupt sources test */
    printf("\n[9] Multiple IRQ sources...\n");
    if (test_multiple_irq_sources() != 0) goto fail;

    /* IRQ control tests */
    printf("\n[10] IRQ masking...\n");
    if (test_irq_masking() != 0) goto fail;

    printf("\n[11] IRQ enable toggle...\n");
    if (test_irq_enable_toggle() != 0) goto fail;

    printf("\nAll KMCSR interrupt tests passed!\n");
    TEST_PASS();

fail:
    /* Restore IRQ mask */
    rom_picorv32_maskirq(old_mask);
    return 0;
}
