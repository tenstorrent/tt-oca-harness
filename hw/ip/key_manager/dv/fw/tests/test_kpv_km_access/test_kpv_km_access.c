/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_km_access.c
 * @brief KPV KM port access test
 *
 * Verifies KM port: every word of a key slot reads back what was written (the
 * KPV masks nothing), and lock_write/lock_use cause access violations
 * (SLVERR).  Also verifies that neither lock bit can be cleared by writing
 * zero, and that a write blocked by lock_write leaves the key value alone.
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

#define SLOT_ID 0
#define WORD_PATTERN(w) (0x11111111u * ((uint32_t)(w) + 1u))

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

    if (!tb_set_timeout(50000)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    TEST_LOG("KPV KM port access test (slot 0)");

    /* -----------------------------------------------------------------------
     * 1. Every word of the slot reads back what was written.  The KPV has no
     *    length field, so no word is masked.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("All 16 words read back unmasked");
    for (uint32_t w = 0; w < 16u; w++) KPV_KEY_WORD_REG(SLOT_ID, w).w = WORD_PATTERN(w);

    for (uint32_t w = 0; w < 16u; w++) {
        uint32_t got = KPV_KEY_WORD_REG(SLOT_ID, w).w;
        if (got != WORD_PATTERN(w)) {
            TEST_FAIL("Word %u readback: expected 0x%08X, got 0x%08X", (unsigned)w, WORD_PATTERN(w),
                      got);
        }
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 2. lock_write: key write blocked (SLVERR) and the key value unchanged.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_write: key write blocked (SLVERR, key unchanged)");
    KPV_CTRL_REG(SLOT_ID).f.lock_write = 1u;
    if (KPV_CTRL_REG(SLOT_ID).f.lock_write != 1u) {
        TEST_FAIL("lock_write not set (ctrl=0x%08X)", (unsigned)KPV_CTRL_REG(SLOT_ID).w);
    }

    clear_axi_slverr();
    KPV_KEY_WORD_REG(SLOT_ID, 0).w = 0xDEADBEEFu; /* Write blocked by lock_write */
    if (!check_axi_slverr_set()) {
        TEST_FAIL("Key write with lock_write should set IRQ_STATUS.AXI_SLVERR");
    }

    uint32_t r0 = KPV_KEY_WORD_REG(SLOT_ID, 0).w;
    if (r0 != WORD_PATTERN(0)) {
        TEST_FAIL("Key should be unchanged after blocked write (got 0x%08X)", r0);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 3. lock_write cannot be cleared (W1S): writing zero has no effect.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_write cannot be cleared (W1S)");
    km_kpv__ctrl_reg_t ctrl_clear_lw = {.w = KPV_CTRL_REG(SLOT_ID).w};
    ctrl_clear_lw.f.lock_write = 0u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_clear_lw.w;

    if (KPV_CTRL_REG(SLOT_ID).f.lock_write != 1u) {
        TEST_FAIL("lock_write must remain set after write with lock_write=0 (ctrl=0x%08X)",
                  (unsigned)KPV_CTRL_REG(SLOT_ID).w);
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 4. lock_use: key read returns 0 and SLVERR.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_use: key read returns 0 and SLVERR");
    KPV_CTRL_REG(SLOT_ID).f.lock_use = 1u;
    if (KPV_CTRL_REG(SLOT_ID).f.lock_use != 1u) {
        TEST_FAIL("lock_use not set (ctrl=0x%08X)", (unsigned)KPV_CTRL_REG(SLOT_ID).w);
    }

    clear_axi_slverr();
    uint32_t after_lock = KPV_KEY_WORD_REG(SLOT_ID, 0).w;
    if (after_lock != 0u) {
        TEST_FAIL("After lock_use, key read should return 0, got 0x%08X", after_lock);
    }
    if (!check_axi_slverr_set()) {
        TEST_FAIL("Key read with lock_use should set IRQ_STATUS.AXI_SLVERR");
    }
    TEST_SUBTEST_PASS();

    /* -----------------------------------------------------------------------
     * 5. lock_use cannot be cleared (W1S): writing zero has no effect.
     * ----------------------------------------------------------------------- */
    TEST_SUBTEST_START("lock_use cannot be cleared (W1S)");
    km_kpv__ctrl_reg_t ctrl_clear_lu = {.w = KPV_CTRL_REG(SLOT_ID).w};
    ctrl_clear_lu.f.lock_use = 0u;
    KPV_CTRL_REG(SLOT_ID).w = ctrl_clear_lu.w;

    if (KPV_CTRL_REG(SLOT_ID).f.lock_use != 1u) {
        TEST_FAIL("lock_use must remain set after write with lock_use=0 (ctrl=0x%08X)",
                  (unsigned)KPV_CTRL_REG(SLOT_ID).w);
    }
    TEST_SUBTEST_PASS();

    TEST_LOG("KPV KM access test done (lock_use/lock_write set; SLVERR on violation)");
    TEST_PASS();
    return 0;
}
