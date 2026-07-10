/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_axi_bad_rw_irq.c
 * @brief Dedicated test for AXI SLVERR on illegal R/W (err_if_bad_rw)
 *
 * Verifies that when the CPU performs an illegal read/write to a KMCSR
 * register (write to read-only register, or read from write-only register),
 * the regblock returns SLVERR and KMCSR sets IRQ_STATUS.AXI_SLVERR. The
 * regblock is generated with --err-if-bad-rw (peakrdl-regblock >= 1.2.0).
 *
 * Subtest 1: Write to read-only DEBUG → SLVERR, IRQ set, W1C
 * Subtest 2: Read from write-only IRQ_SET → SLVERR, IRQ set, W1C
 *
 * Run with:
 *   make run_fw FW_TEST=test_axi_bad_rw_irq
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DEBUG is read-only (all fields sw=r). Writing triggers SLVERR when err_if_bad_rw enabled. */
#define KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR_PTR \
    ((volatile uint32_t *)KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR)
/* IRQ_SET is write-only (all fields sw=w). Reading triggers SLVERR when err_if_bad_rw enabled. */
#define KMCSR_IRQ_SET_REG_ADDR_PTR ((volatile uint32_t *)KEY_MANAGER_KMCSR_IRQ_SET_BASE_ADDR)

int main(void) {
    uint32_t irq_status;

    TEST_INIT();

    printf("AXI SLVERR on Illegal R/W Test (err_if_bad_rw)\n");
    printf("===============================================\n\n");

    /* Clear any existing AXI SLVERR sticky bit */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }

    /* Verify IRQ is clear at the beginning of the test */
    irq_status = rom_kmcsr_irq_status_read();
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(!status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be clear at test start (status=0x%08X)",
                    irq_status);
    }
    TEST_LOG("  Verified IRQ_STATUS.AXI_SLVERR is clear at start");

    /*=========================================================================
     * Subtest 1: Write to read-only DEBUG register → SLVERR
     *=========================================================================*/
    TEST_SUBTEST_START("Write to read-only DEBUG → SLVERR");
    TEST_LOG("  Writing 0xDEADBEEF to read-only DEBUG register at 0x%08X...",
             KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR);
    *KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR_PTR = 0xDEADBEEFu;

    /* Verify IRQ_STATUS.AXI_SLVERR is set */
    irq_status = rom_kmcsr_irq_status_read();
    TEST_LOG("  KMCSR IRQ_STATUS = 0x%08X", irq_status);
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be set after write to RO DEBUG (status=0x%08X)",
                    irq_status);
    }

    /* Clear the sticky bit (W1C) */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }
    irq_status = rom_kmcsr_irq_status_read();
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(!status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be clear after W1C (status=0x%08X)", irq_status);
    }
    TEST_LOG("  AXI SLVERR set and W1C OK after write to RO DEBUG");
    TEST_SUBTEST_PASS();

    /*=========================================================================
     * Subtest 2: Read from write-only IRQ_SET register → SLVERR
     *=========================================================================*/
    TEST_SUBTEST_START("Read from write-only IRQ_SET → SLVERR");
    TEST_LOG("  Reading from write-only IRQ_SET register at 0x%08X...",
             KEY_MANAGER_KMCSR_IRQ_SET_BASE_ADDR);
    (void)*KMCSR_IRQ_SET_REG_ADDR_PTR;

    /* Verify IRQ_STATUS.AXI_SLVERR is set */
    irq_status = rom_kmcsr_irq_status_read();
    TEST_LOG("  KMCSR IRQ_STATUS = 0x%08X", irq_status);
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be set after read from WO IRQ_SET (status=0x%08X)",
                    irq_status);
    }

    /* Clear the sticky bit (W1C) */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }
    irq_status = rom_kmcsr_irq_status_read();
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(!status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be clear after W1C (status=0x%08X)", irq_status);
    }
    TEST_LOG("  AXI SLVERR set and W1C OK after read from WO IRQ_SET");
    TEST_SUBTEST_PASS();

    TEST_LOG("  AXI SLVERR on illegal R/W (err_if_bad_rw) verified");
    TEST_PASS();
    return 0;
}
