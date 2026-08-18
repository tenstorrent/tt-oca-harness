/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_km_store_lock.c
 * @brief KM store/read/lock flow
 *
 * KM writes key slot, reads back, sets lock_write/lock_use, verifies subsequent
 * key write/read blocked (SLVERR). Verifies lock_write blocks CTRL metadata
 * (extend, dest_valid, last_dword) from update (CTRL writes return OKAY, not
 * SLVERR). Verifies lock_write and lock_use cannot be cleared (W1S).
 *
 * Run with: make run_fw FW_TEST=test_kpv_km_store_lock
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

#define SLOT_ID 1
#define CTRL_EXTEND_VAL 2u
#define CTRL_LAST_DWORD_VAL 3u /* words 0..3 valid */

static void clear_axi_slverr(void) {
    km_csr__irq_status_reg_t clear_val = {0};
    clear_val.f.axi_slverr = 1;
    rom_kmcsr_irq_status_clear(clear_val.w);
}

static int check_axi_slverr_set(void) {
    km_csr__irq_status_reg_t s = {.w = rom_kmcsr_irq_status_read()};
    return s.f.axi_slverr != 0u;
}

int main(void) {
    TEST_INIT();
    if (!tb_set_timeout(50000)) TEST_FAIL("timeout");

    /* -----------------------------------------------------------------------
     * 1. Store key data and CTRL metadata (extend and last_dword).
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("Store key and CTRL, read back");
    KPV_KEY_WORD_REG(SLOT_ID, 0).w = 0xCAFEBABEu;
    KPV_KEY_WORD_REG(SLOT_ID, 1).w = 0xDEADBEEFu;
    KPV_KEY_WORD_REG(SLOT_ID, 2).w = 0x12345678u;
    KPV_KEY_WORD_REG(SLOT_ID, 3).w = 0xABCDEF00u;

    km_kpv__ctrl_reg_t ctrl = {.w = 0u};
    ctrl.f.last_dword = CTRL_LAST_DWORD_VAL;
    ctrl.f.extend = CTRL_EXTEND_VAL;
    KPV_CTRL_REG(SLOT_ID).w = ctrl.w;

    uint32_t r0 = KPV_KEY_WORD_REG(SLOT_ID, 0).w;
    uint32_t r1 = KPV_KEY_WORD_REG(SLOT_ID, 1).w;
    if (r0 != 0xCAFEBABEu || r1 != 0xDEADBEEFu) {
        TEST_FAIL("Key readback: expected 0xCAFEBABE/0xDEADBEEF, got 0x%08X/0x%08X", r0, r1);
    }
    km_kpv__ctrl_reg_t ctrl_read = {.w = KPV_CTRL_REG(SLOT_ID).w};
    if (ctrl_read.f.last_dword != CTRL_LAST_DWORD_VAL || ctrl_read.f.extend != CTRL_EXTEND_VAL) {
        TEST_FAIL("CTRL readback: extend=0x%X last_dword=0x%X", (unsigned)ctrl_read.f.extend,
                  (unsigned)ctrl_read.f.last_dword);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 2. Set lock_write. Verify key write blocked (SLVERR, key unchanged).
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_write: key write blocked (SLVERR, key unchanged)");
    ctrl_read.f.lock_write = 1u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_read.w;

    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.lock_write != 1u) {
        TEST_FAIL("lock_write not set (ctrl=0x%08X)", ctrl_read.w);
    }

    clear_axi_slverr();
    KPV_KEY_WORD_REG(SLOT_ID, 0).w = 0x11111111u;
    if (!check_axi_slverr_set()) {
        TEST_FAIL("Key write with lock_write should set IRQ_STATUS.AXI_SLVERR");
    }
    r0 = KPV_KEY_WORD_REG(SLOT_ID, 0).w;
    if (r0 != 0xCAFEBABEu) {
        TEST_FAIL("Key should be unchanged after blocked write (got 0x%08X)", r0);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 3. lock_write: CTRL metadata write blocked (OKAY, metadata unchanged).
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_write: CTRL metadata write blocked (OKAY, metadata unchanged)");
    km_kpv__ctrl_reg_t ctrl_try = {.w = KPV_CTRL_REG(SLOT_ID).w};
    ctrl_try.f.last_dword = 0u;
    ctrl_try.f.extend = 0u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_try.w;

    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.last_dword != CTRL_LAST_DWORD_VAL || ctrl_read.f.extend != CTRL_EXTEND_VAL) {
        TEST_FAIL("CTRL metadata should be unchanged after write (last_dword=0x%X extend=0x%X)",
                  (unsigned)ctrl_read.f.last_dword, (unsigned)ctrl_read.f.extend);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 4. lock_write and lock_use cannot be cleared (W1S): write 0 has no effect.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_write cannot be cleared (W1S)");
    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.lock_write != 1u) {
        TEST_FAIL("lock_write not set before clear attempt (ctrl=0x%08X)", ctrl_read.w);
    }
    /* Attempt to clear lock_write by writing CTRL with lock_write=0 */
    km_kpv__ctrl_reg_t ctrl_clear_lw = {.w = KPV_CTRL_REG(SLOT_ID).w};
    ctrl_clear_lw.f.lock_write = 0u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_clear_lw.w;
    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.lock_write != 1u) {
        TEST_FAIL("lock_write must remain set after write with lock_write=0 (ctrl=0x%08X)",
                  ctrl_read.w);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 5. Set lock_use. Verify key read returns 0 and SLVERR.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_use: key read returns 0 and SLVERR");
    ctrl_read.f.lock_use = 1u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_read.w;

    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.lock_use != 1u) {
        TEST_FAIL("lock_use not set (ctrl=0x%08X)", ctrl_read.w);
    }

    clear_axi_slverr();
    uint32_t after_lock_use = KPV_KEY_WORD_REG(SLOT_ID, 0).w;
    if (after_lock_use != 0u) {
        TEST_FAIL("After lock_use, key read should return 0, got 0x%08X", after_lock_use);
    }
    if (!check_axi_slverr_set()) {
        TEST_FAIL("Key read with lock_use should set IRQ_STATUS.AXI_SLVERR");
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 6. lock_use cannot be cleared (W1S): write 0 has no effect.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_use cannot be cleared (W1S)");
    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.lock_use != 1u) {
        TEST_FAIL("lock_use not set before clear attempt (ctrl=0x%08X)", ctrl_read.w);
    }
    /* Attempt to clear lock_use by writing CTRL with lock_use=0 */
    km_kpv__ctrl_reg_t ctrl_clear_lu = {.w = KPV_CTRL_REG(SLOT_ID).w};
    ctrl_clear_lu.f.lock_use = 0u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_clear_lu.w;
    ctrl_read.w = KPV_CTRL_REG(SLOT_ID).w;
    if (ctrl_read.f.lock_use != 1u) {
        TEST_FAIL("lock_use must remain set after write with lock_use=0 (ctrl=0x%08X)",
                  ctrl_read.w);
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
