/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_axi_decerr_irq.c
 * @brief Dedicated test for AXI DECERR response and KMCSR IRQ status
 *
 * Verifies that an CPU access to an unmapped address causes the AXI
 * interconnect to return DECERR, and that KMCSR IRQ_STATUS.AXI_DECERR
 * is set. The test does not rely on IRQ_SET; it provokes a real bus
 * DECERR by reading from an address in the reserved/unmapped region
 * (0x0001_D000 and above per key_manager.rdl).
 *
 * Requirements: AXI DECERR detection (T069–T072), firmware test T074
 *
 * Run with:
 *   make run_fw FW_TEST=test_axi_decerr_irq
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* First unmapped address after the ABR window (0x0001_C000-0x0001_CFFF);
 * accesses here return AXI DECERR */
#define UNMAPPED_DECERR_ADDR 0x0001D000U

/**
 * Trigger a bus DECERR by reading from an unmapped address.
 * The CPU AXI transaction will get DECERR; picorv32_wrapper
 * drives axi_decerr_o and KMCSR sets IRQ_STATUS.AXI_DECERR.
 */
static inline void access_unmapped_read(void) {
    (void)*(volatile uint32_t *)UNMAPPED_DECERR_ADDR;
}

int main(void) {
    uint32_t irq_status;

    TEST_INIT();

    printf("AXI DECERR IRQ Status Test\n");
    printf("==========================\n\n");

    /* Clear any existing AXI DECERR sticky bit */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_decerr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }

    /* Verify IRQ is clear at the beginning of the test */
    irq_status = rom_kmcsr_irq_status_read();
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(!status_reg.f.axi_decerr,
                    "IRQ_STATUS.AXI_DECERR must be clear at test start (status=0x%08X)",
                    irq_status);
    }
    TEST_LOG("  Verified IRQ_STATUS.AXI_DECERR is clear at start");

    /* Cause a real bus DECERR by reading from unmapped address */
    TEST_LOG("  Reading from unmapped address 0x%08X to trigger DECERR...", UNMAPPED_DECERR_ADDR);
    access_unmapped_read();

    /* Verify IRQ_STATUS.AXI_DECERR is set */
    irq_status = rom_kmcsr_irq_status_read();
    TEST_LOG("  KMCSR IRQ_STATUS = 0x%08X", irq_status);
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(status_reg.f.axi_decerr,
                    "IRQ_STATUS.AXI_DECERR must be set after unmapped read (status=0x%08X)",
                    irq_status);
    }

    /* Clear the sticky bit (W1C) */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_decerr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }

    irq_status = rom_kmcsr_irq_status_read();
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(!status_reg.f.axi_decerr,
                    "IRQ_STATUS.AXI_DECERR must be clear after W1C (status=0x%08X)", irq_status);
    }

    TEST_LOG("  AXI DECERR IRQ status set and cleared successfully");
    TEST_PASS();
    return 0;
}
