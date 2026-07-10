/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_axi_slverr_irq.c
 * @brief Dedicated test for AXI SLVERR response from KMCSR unmapped register
 *
 * Verifies that a CPU write to a non-existent register within KMCSR's address
 * space causes the register block to return SLVERR, and that KMCSR
 * IRQ_STATUS.AXI_SLVERR is set. The test writes to the address immediately
 * before the DEBUG register (0xE1F8), which is unmapped within KMCSR's 4KB
 * space. The regblock is generated with --err-if-bad-addr (peakrdl-regblock
 * >= 1.2.0) so it returns SLVERR for that offset.
 *
 * Requirements: AXI SLVERR detection (T069–T072), firmware test T073
 *
 * Run with:
 *   make run_fw FW_TEST=test_axi_slverr_irq
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* DEBUG register is at offset 0x1FC (0xE1FC). Unmapped slot just before it: 0x1F8 (0xE1F8) */
#define KMCSR_UNMAPPED_REG_ADDR (KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR - 4U)

/**
 * Trigger a bus SLVERR by writing to an unmapped register within KMCSR.
 * The CPU AXI transaction gets SLVERR from the regblock (generated with
 * --err-if-bad-addr); picorv32_wrapper drives axi_slverr_o and KMCSR
 * sets IRQ_STATUS.AXI_SLVERR.
 */
static inline void write_unmapped_kmcsr_reg(uint32_t addr, uint32_t data) {
    *(volatile uint32_t *)addr = data;
}

int main(void) {
    uint32_t irq_status;

    TEST_INIT();

    printf("AXI SLVERR IRQ Status Test (KMCSR unmapped register)\n");
    printf("====================================================\n\n");

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

    /* Cause a real bus SLVERR by writing to unmapped register within KMCSR */
    TEST_LOG(
        "  Writing 0xDEADBEEF to unmapped KMCSR register at 0x%08X (just before DEBUG @ 0x%08X)...",
        KMCSR_UNMAPPED_REG_ADDR, KEY_MANAGER_KMCSR_DEBUG_BASE_ADDR);
    write_unmapped_kmcsr_reg(KMCSR_UNMAPPED_REG_ADDR, 0xDEADBEEF);

    /* Verify IRQ_STATUS.AXI_SLVERR is set */
    irq_status = rom_kmcsr_irq_status_read();
    TEST_LOG("  KMCSR IRQ_STATUS = 0x%08X", irq_status);
    {
        km_csr__irq_status_reg_t status_reg;
        status_reg.w = irq_status;
        TEST_ASSERT(status_reg.f.axi_slverr,
                    "IRQ_STATUS.AXI_SLVERR must be set after unmapped KMCSR write (status=0x%08X)",
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

    TEST_LOG("  AXI SLVERR IRQ status set and cleared successfully");
    TEST_PASS();
    return 0;
}
