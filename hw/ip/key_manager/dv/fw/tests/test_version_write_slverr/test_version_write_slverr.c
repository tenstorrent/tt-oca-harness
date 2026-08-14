/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_version_write_slverr.c
 * @brief VERSION register write → SLVERR and value unchanged
 *
 * Verifies that writes to the read-only VERSION register:
 * - Complete with AXI SLVERR (IRQ_STATUS.AXI_SLVERR set when err_if_bad_rw enabled)
 * - Do not change the register value (re-read yields 1.0.0 / 0x0001_0000)
 *
 * Run with:
 *   make run_fw FW_TEST=test_version_write_slverr
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define KMCSR_VERSION_REG_ADDR_PTR ((volatile uint32_t *)KEY_MANAGER_KMCSR_VERSION_BASE_ADDR)
#define VERSION_EXPECTED_VAL (0x00010000u) /* 0x0001_0000 = 1.0.0 */

int main(void) {
    uint32_t irq_status;
    uint32_t version_before;
    uint32_t version_after;

    TEST_INIT();

    printf("VERSION Write SLVERR Test\n");
    printf("==================================\n\n");

    /* Clear any existing AXI SLVERR sticky bit */
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
                    "IRQ_STATUS.AXI_SLVERR must be clear at test start (status=0x%08X)",
                    irq_status);
    }

    /* Read VERSION before write */
    version_before = *KMCSR_VERSION_REG_ADDR_PTR;
    TEST_LOG("  VERSION before write = 0x%08X", version_before);
    TEST_ASSERT_EQ(version_before, VERSION_EXPECTED_VAL,
                   "VERSION must read 1.0.0 (0x0001_0000) before write");

    /* Write to read-only VERSION → must trigger SLVERR */
    TEST_LOG("  Writing 0xDEADBEEF to read-only VERSION at 0x%08X...",
             KEY_MANAGER_KMCSR_VERSION_BASE_ADDR);
    *KMCSR_VERSION_REG_ADDR_PTR = 0xDEADBEEFu;

    /* Verify IRQ_STATUS.AXI_SLVERR is set */
    irq_status = rom_kmcsr_irq_status_read();
    TEST_LOG("  KMCSR IRQ_STATUS = 0x%08X", irq_status);
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be set after write to RO VERSION (status=0x%08X)",
                    irq_status);
    }

    /* Re-read VERSION: value must be unchanged (1.0.0) */
    version_after = *KMCSR_VERSION_REG_ADDR_PTR;
    TEST_LOG("  VERSION after write = 0x%08X (expected 0x%08X)", version_after,
             VERSION_EXPECTED_VAL);
    TEST_ASSERT_EQ(version_after, VERSION_EXPECTED_VAL,
                   "VERSION must remain 0x0001_0000 after write (unchanged)");

    /* Clear sticky for clean exit */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }

    TEST_LOG("  VERSION write SLVERR and value unchanged verified");
    TEST_PASS();
    return 0;
}
