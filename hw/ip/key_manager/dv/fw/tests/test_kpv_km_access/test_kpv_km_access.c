/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_km_access.c
 * @brief KPV KM port access test
 *
 * Verifies KM port: write/read key slot and control; lock_write/lock_use
 * cause access violations (SLVERR). This test does basic read/write and
 * lock; SLVERR on violation is observable via testbench or AXI response.
 *
 * Run with:
 *   make run_fw FW_TEST=test_kpv_km_access
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

/* KPV (KM port) register struct access (from km_kpv.h) */
#define KPV_KEY_WORD_ADDR(slot, word) \
    (KEY_MANAGER_KPV_BASE_ADDR + (uint32_t)(slot)*KEY_MANAGER_KPV_KEY_ENTRY_SIZE + \
     (uint32_t)(word)*4u)
#define KPV_KEY_WORD_REG(slot, word) \
    (*(volatile km_kpv__key_word_reg_t *)KPV_KEY_WORD_ADDR(slot, word))
#define KPV_CTRL_ADDR(slot) (KEY_MANAGER_KPV_CTRL_BASE_ADDR(0) + (uint32_t)(slot)*4u)
#define KPV_CTRL_REG(slot) (*(volatile km_kpv__ctrl_reg_t *)KPV_CTRL_ADDR(slot))

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(50000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    TEST_LOG("KPV KM port access test (slot 0)");

    /* Write multiple key words to slot 0 (words 0..4) */
    KPV_KEY_WORD_REG(0, 0).w = 0x11111111u;
    KPV_KEY_WORD_REG(0, 1).w = 0x22222222u;
    KPV_KEY_WORD_REG(0, 2).w = 0x33333333u;
    KPV_KEY_WORD_REG(0, 3).w = 0x44444444u;
    KPV_KEY_WORD_REG(0, 4).w = 0x55555555u;
    /* Set last_dword = 2 so words 0..2 are valid; words 3+ must read as 0 */
    KPV_CTRL_REG(0).f.last_dword = 2u;

    /* Read back within range: must see written values */
    uint32_t r0 = KPV_KEY_WORD_REG(0, 0).w;
    uint32_t r1 = KPV_KEY_WORD_REG(0, 1).w;
    uint32_t r2 = KPV_KEY_WORD_REG(0, 2).w;
    if (r0 != 0x11111111u || r1 != 0x22222222u || r2 != 0x33333333u) {
        TEST_FAIL("Key readback in range: expected 0x11111111/0x22222222/0x33333333, got "
                  "0x%08X/0x%08X/0x%08X",
                  r0, r1, r2);
    }

    /* Read beyond last_dword: must return 0 (masked) */
    uint32_t r3 = KPV_KEY_WORD_REG(0, 3).w;
    uint32_t r4 = KPV_KEY_WORD_REG(0, 4).w;
    if (r3 != 0u || r4 != 0u) {
        TEST_FAIL("Words beyond last_dword must return 0: word3=0x%08X word4=0x%08X", r3, r4);
    }

    /* Set last_dword = 1 for remainder of test (words 0..1 valid) */
    KPV_CTRL_REG(0).f.last_dword = 1u;
    r0 = KPV_KEY_WORD_REG(0, 0).w;
    r1 = KPV_KEY_WORD_REG(0, 1).w;
    if (r0 != 0x11111111u || r1 != 0x22222222u) {
        TEST_FAIL("Key readback: expected 0x11111111/0x22222222, got 0x%08X/0x%08X", r0, r1);
    }

    /* Set lock_use (W1S): KM read of key data should then return SLVERR */
    KPV_CTRL_REG(0).f.lock_use = 1u;
    if (KPV_CTRL_REG(0).f.lock_use != 1u) {
        TEST_FAIL("lock_use not set (ctrl=0x%08X)", (unsigned)KPV_CTRL_REG(0).w);
    }

    /* Clear KMCSR IRQ_STATUS.AXI_SLVERR so we can verify it is set by the next read */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }

    /* Read key: with lock_use set, access returns SLVERR (IRQ_STATUS.axi_slverr set) and data 0 */
    uint32_t after_lock = KPV_KEY_WORD_REG(0, 0).w;
    if (after_lock != 0u) {
        TEST_FAIL("After lock_use, key read should return 0, got 0x%08X", after_lock);
    }
    {
        uint32_t irq_status = rom_kmcsr_irq_status_read();
        km_csr__irq_status_reg_t s = {.w = irq_status};
        if (!s.f.axi_slverr) {
            TEST_FAIL(
                "After lock_use key read, IRQ_STATUS.AXI_SLVERR should be set (status=0x%08X)",
                irq_status);
        }
    }

    /* Set lock_write: KM write to key/ctrl should then return SLVERR */
    KPV_CTRL_REG(0).f.lock_write = 1u;
    if (KPV_CTRL_REG(0).f.lock_write != 1u) {
        TEST_FAIL("lock_write not set (ctrl=0x%08X)", (unsigned)KPV_CTRL_REG(0).w);
    }

    /* Clear AXI_SLVERR, then attempt write to key; write must be blocked (SLVERR) */
    {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }
    KPV_KEY_WORD_REG(0, 0).w = 0xDEADBEEFu; /* Write blocked by lock_write */
    {
        uint32_t irq_status = rom_kmcsr_irq_status_read();
        km_csr__irq_status_reg_t s = {.w = irq_status};
        if (!s.f.axi_slverr) {
            TEST_FAIL(
                "After lock_write, key write should set IRQ_STATUS.AXI_SLVERR (status=0x%08X)",
                irq_status);
        }
    }

    TEST_LOG("KPV KM access test done (lock_use/lock_write set; SLVERR on violation)");
    TEST_PASS();
    return 0;
}
