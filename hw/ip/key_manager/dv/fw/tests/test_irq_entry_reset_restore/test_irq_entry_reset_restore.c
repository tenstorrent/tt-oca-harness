/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_irq_entry_reset_restore.c
 * @brief External async reset (TB rst_n) and KM soft reset restore IRQ_ENTRY_ADDR / IRQ_ENTRY_LOCK.
 *
 * Phase is stored in SRAM (retained across TB warm reset; see tb_key_manager SRAM model).
 */

#include "test_common.h"

#define SOFT_RST_CODE_MAGIC 0x53525354u

#define PHASE_ADDR (SRAM_BASE + 0x2E00u)

/** @brief SRAM-resident phase marker for TB async reset vs KM soft reset legs. */
enum phase {
    PHASE_INIT = 0,
    PHASE_POST_ASYNC = 0xA1u,
    PHASE_POST_SOFT = 0xB2u,
};

/**
 * @brief Verify IRQ_ENTRY CSRs after external async reset and after KM soft reset.
 *
 * @return Does not return on success; halts via TEST_PASS or TEST_FAIL.
 */
int main(void) {
    TEST_INIT();

    volatile uint32_t *phase = (volatile uint32_t *)PHASE_ADDR;

    if (*phase == PHASE_INIT) {
        TEST_SUBTEST_START("External async reset restores defaults");
        irq_entry_addr_write(0x00005000u);
        irq_entry_lock_write1();
        if (irq_entry_addr_read() != 0x5000u || irq_entry_lock_read() != 1u) {
            TEST_FAIL("program before async reset: addr=0x%08X lock=%u", irq_entry_addr_read(),
                      irq_entry_lock_read());
        }
        *phase = PHASE_POST_ASYNC;
        TB_CMD_STATUS = TB_STATUS_IDLE;
        TB_CMD_ARG = 0;
        TB_CMD = TB_CMD_KM_ASYNC_RESET;
        for (;;) {
            __asm__ volatile("nop");
        }
    }

    if (*phase == PHASE_POST_ASYNC) {
        if (irq_entry_addr_read() != 0x10u || irq_entry_lock_read() != 0u) {
            TEST_FAIL("after async reset: addr=0x%08X lock=%u", irq_entry_addr_read(),
                      irq_entry_lock_read());
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("KM soft reset restores defaults");
        irq_entry_addr_write(0x00006000u);
        irq_entry_lock_write1();
        if (irq_entry_addr_read() != 0x6000u || irq_entry_lock_read() != 1u) {
            TEST_FAIL("program before soft reset: addr=0x%08X lock=%u", irq_entry_addr_read(),
                      irq_entry_lock_read());
        }
        *phase = PHASE_POST_SOFT;
        *(volatile uint32_t *)KEY_MANAGER_KMCSR_SOFT_RST_CODE_BASE_ADDR = SOFT_RST_CODE_MAGIC;
        TEST_FAIL("execution continued after soft reset");
        return 1;
    }

    if (*phase == PHASE_POST_SOFT) {
        if (irq_entry_addr_read() != 0x10u || irq_entry_lock_read() != 0u) {
            TEST_FAIL("after soft reset: addr=0x%08X lock=%u", irq_entry_addr_read(),
                      irq_entry_lock_read());
        }
        TEST_SUBTEST_PASS();
        TEST_PASS();
        return 0;
    }

    TEST_FAIL("unexpected phase 0x%08X", *phase);
    return 1;
}
