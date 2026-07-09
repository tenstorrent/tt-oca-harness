/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_irq_entry_lock.c
 * @brief IRQ_ENTRY_LOCK write-1-only and post-lock ignored writes with stable readback.
 */

#include "test_common.h"

/**
 * @brief Verify IRQ_ENTRY_LOCK write-1 semantics and post-lock addr behavior.
 *
 * @return Does not return; halts via TEST_PASS or TEST_FAIL.
 */
int main(void) {
    TEST_INIT();

    TEST_SUBTEST_START("Lock write-1-only and post-lock addr writes ignored");
    irq_entry_addr_write(0x00000200u);
    if (irq_entry_addr_read() != 0x200u) {
        TEST_FAIL("pre-lock addr: 0x%08X", irq_entry_addr_read());
    }

    irq_entry_lock_write1();
    if (irq_entry_lock_read() != 1u) {
        TEST_FAIL("lock not set (got %u)", irq_entry_lock_read());
    }

    /* Write 0 to lock must not clear */
    {
        volatile km_csr__irq_entry_lock_reg_t *lock_reg =
            (volatile km_csr__irq_entry_lock_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_LOCK_BASE_ADDR;
        km_csr__irq_entry_lock_reg_t z = {0};
        lock_reg->w = z.w;
    }
    if (irq_entry_lock_read() != 1u) {
        TEST_FAIL("lock cleared incorrectly (got %u)", irq_entry_lock_read());
    }

    irq_entry_addr_write(0x00000300u);
    if (irq_entry_addr_read() != 0x200u) {
        TEST_FAIL("post-lock addr changed: 0x%08X", irq_entry_addr_read());
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
