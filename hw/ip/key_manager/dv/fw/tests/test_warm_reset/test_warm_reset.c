/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_warm_reset.c
 * @brief Dual warm-reset source coverage and per-component verification.
 *
 * This test runs through three sequential firmware phases across two warm
 * resets to verify that:
 *   - Warm reset from the external warm_rst_n port (via TB_CMD_KM_WARM_RESET)
 *     correctly resets warm-resettable KMCSR and KPV state.
 *   - Warm reset from the SOFT_RST_CODE register correctly triggers the same
 *     reset and does not loop (SOFT_RST_CODE is itself warm-resettable).
 *   - State that is warm-resettable (IRQ_ENABLE, IRQ_ENTRY_ADDR, KPV lock bits,
 *     SRAM_LOCK write-lock bits) is zero after each warm reset.
 *   - COLD_BOOT_DONE (woset, cold-reset-only) remains 1 across warm resets
 *     because ROM re-sets it at the top of each boot sequence.
 *   - SRAM content (cold-only storage) is preserved across warm resets.
 *
 * Phase detection:
 *   A 32-bit marker is written to a stable SRAM location before each warm
 *   reset.  On restart the firmware reads the marker to determine which phase
 *   is in progress.
 *
 * Phase 0 — cold boot (marker == 0):
 *   1. Verify COLD_BOOT_DONE == 1 (ROM sets it unconditionally at cold boot).
 *   2. Set IRQ_ENABLE, program IRQ_ENTRY_ADDR, set KPV slot-0 lock bits, set SRAM_LOCK.
 *   3. Write SRAM marker = MARKER_PHASE1.
 *   4. Issue TB_CMD_KM_WARM_RESET → CPU restarts via external warm_rst_n.
 *
 * Phase 1 — after warm-from-external (marker == MARKER_PHASE1):
 *   1. Verify SRAM marker persists (SRAM is cold-only).
 *   2. Verify IRQ_ENABLE == 0 (warm-reset cleared).
 *   3. Verify IRQ_ENTRY_ADDR == 0x10 (reset default; warm-reset cleared).
 *   4. Verify KPV slot-0 lock_write == 0 and lock_use == 0 (warm-reset cleared).
 *   5. Verify SRAM_LOCK == 0 (warm-reset cleared).
 *   6. Verify COLD_BOOT_DONE == 1 (ROM re-set it; warm reset did not clear it).
 *   7. Set IRQ_ENABLE, re-program IRQ_ENTRY_ADDR, set KPV slot-0 lock bits, set SRAM_LOCK again.
 *   8. Write SRAM marker = MARKER_PHASE2.
 *   9. Write SOFT_RST_CODE = MAGIC → CPU restarts via warm reset from soft.
 *      (SOFT_RST_CODE clears to 0 on warm reset, preventing an infinite loop.)
 *
 * Phase 2 — after warm-from-soft (marker == MARKER_PHASE2):
 *   1. Verify SRAM marker persists.
 *   2. Verify IRQ_ENABLE == 0.
 *   3. Verify IRQ_ENTRY_ADDR == 0x10 (reset default).
 *   4. Verify KPV slot-0 lock_write == 0 and lock_use == 0.
 *   5. Verify SRAM_LOCK == 0.
 *   6. Verify COLD_BOOT_DONE == 1.
 *   7. TEST_PASS.
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "rom_kpv.h"

/*===========================================================================
 * Constants
 *===========================================================================*/

/* Soft reset magic ("SRST" in ASCII) — must match km_csr.sv */
#define SOFT_RST_CODE_MAGIC 0x53525354u

/* SRAM word used as phase marker.
 * Must be below BSS_START so crt0.s does not clear it
 * when it re-executes after each warm reset (crt0 only clears the .bss
 * section, not the full SRAM).  Convention in this TB: use an address in
 * the mid-SRAM range that is also well above any plausible stack depth.
 * See test_soft_reset.c (+0x3000) and test_irq_entry_reset_restore.c
 * (+0x2E00) for the same pattern. */
#define MARKER_ADDR (SRAM_BASE + 0x2C00u)
#define MARKER_PHASE1 0xAA000001u
#define MARKER_PHASE2 0xAA000002u

/* A non-zero IRQ entry address used to test warm-reset clearing */
#define TEST_IRQ_ENTRY_ADDR 0x10000100u

/* SRAM write-lock region used to test warm-reset clearing.
 * Region 5 covers 0x9400-0x97FF — well below BSS/data/stack (packed from top
 * of SRAM) and not the phase-marker region (11) or region 15 (locking it hangs).
 * Only the lock bit is set and checked; nothing writes into the locked region. */
#define TEST_SRAM_LOCK_REGION 5u
#define TEST_SRAM_LOCK_MASK (1u << TEST_SRAM_LOCK_REGION)

/*===========================================================================
 * Direct register access helpers
 *===========================================================================*/

static inline uint32_t irq_enable_read(void) {
    volatile km_csr__irq_enable_reg_t *r =
        (volatile km_csr__irq_enable_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR;
    return r->w;
}

static inline void irq_enable_write(uint32_t v) {
    volatile km_csr__irq_enable_reg_t *r =
        (volatile km_csr__irq_enable_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR;
    r->w = v;
}

static inline uint32_t kpv_ctrl0_lock_write_read(void) {
    return KPV_CTRL(0u).f.lock_write;
}

static inline uint32_t kpv_ctrl0_lock_use_read(void) {
    return KPV_CTRL(0u).f.lock_use;
}

static inline void kpv_ctrl0_lock_write_set(void) {
    km_kpv__ctrl_reg_t w = KPV_CTRL(0u);
    w.f.lock_write = 1u;
    KPV_CTRL(0u) = w;
}

static inline void kpv_ctrl0_lock_use_set(void) {
    km_kpv__ctrl_reg_t w = KPV_CTRL(0u);
    w.f.lock_use = 1u;
    KPV_CTRL(0u) = w;
}

/*===========================================================================
 * Phase helpers — program warm-resettable state
 *===========================================================================*/

/**
 * @brief Set a known non-zero state in all warm-resettable registers under test.
 *
 * Writes a non-zero value to IRQ_ENABLE, IRQ_ENTRY_ADDR, KPV slot-0 lock bits,
 * and SRAM_LOCK.  Called before each warm reset so the subsequent verification
 * has something meaningful to check.
 */
static void set_warm_resettable_state(void) {
    /* Enable at least one IRQ bit */
    km_csr__irq_enable_reg_t en = {0};
    en.f.rom_parity_en = 1u;
    irq_enable_write(en.w);

    /* Program IRQ entry address */
    irq_entry_addr_write(TEST_IRQ_ENTRY_ADDR);

    /* Set KPV slot-0 lock bits (sticky-set, cleared only by warm/cold reset) */
    kpv_ctrl0_lock_write_set();
    kpv_ctrl0_lock_use_set();

    /* Set SRAM write-lock for a safe region (warm reset domain) */
    rom_kmcsr_sram_lock_set(TEST_SRAM_LOCK_MASK);
}

/* Reset value of IRQ_ENTRY_ADDR.ADDR (ROM IRQ vector default PC = 0x10). */
#define IRQ_ENTRY_ADDR_RESET 0x10u

/**
 * @brief Verify all warm-resettable registers are at their reset values.
 *
 * Fails the test immediately if any register retains its pre-reset value.
 * Note: IRQ_ENTRY_ADDR resets to 0x10 (ROM vector default), not 0.
 */
static void verify_warm_resettable_cleared(void) {
    uint32_t irq_en = irq_enable_read();
    uint32_t entry_addr = irq_entry_addr_read();
    uint32_t lw = kpv_ctrl0_lock_write_read();
    uint32_t lu = kpv_ctrl0_lock_use_read();
    uint32_t sram_lock = rom_kmcsr_sram_lock_read();

    if (irq_en != 0u) {
        TEST_FAIL("IRQ_ENABLE not cleared by warm reset: 0x%08X", (unsigned)irq_en);
    }
    if (entry_addr != IRQ_ENTRY_ADDR_RESET) {
        TEST_FAIL("IRQ_ENTRY_ADDR not at reset default (0x%08X) after warm reset: 0x%08X",
                  (unsigned)IRQ_ENTRY_ADDR_RESET, (unsigned)entry_addr);
    }
    if (lw != 0u) {
        TEST_FAIL("KPV CTRL[0].lock_write not cleared by warm reset");
    }
    if (lu != 0u) {
        TEST_FAIL("KPV CTRL[0].lock_use not cleared by warm reset");
    }
    if (sram_lock != 0u) {
        TEST_FAIL("SRAM_LOCK not cleared by warm reset: 0x%08X", (unsigned)sram_lock);
    }
}

/*===========================================================================
 * main
 *===========================================================================*/

int main(void) {
    TEST_INIT();

    /*
     * Simulate what production rom_boot_init() does: set COLD_BOOT_DONE at
     * the start of every boot sequence (cold and warm).  In production
     * firmware, rom_main.c calls rom_boot_init() which calls this.  Test
     * firmware provides its own main(), so we call it explicitly here.
     * The field is woset so this is safe and idempotent on warm restarts.
     */
    rom_kmcsr_cold_boot_done_set();

    volatile uint32_t *marker = (volatile uint32_t *)MARKER_ADDR;
    uint32_t phase = *marker;

    if (phase == 0u) {
        /*====================================================================
         * Phase 0: cold boot
         *====================================================================*/
        TEST_SUBTEST_START("Phase 0: cold boot state verification");

        TEST_ASSERT_EQ(tb_cold_boot_done_read(), 1u, "COLD_BOOT_DONE after cold boot");

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: program warm-resettable state");

        set_warm_resettable_state();

        /* Sanity: verify the writes took effect before we reset */
        TEST_ASSERT_NE(irq_enable_read(), 0u, "IRQ_ENABLE set before reset");
        TEST_ASSERT_EQ(irq_entry_addr_read(), TEST_IRQ_ENTRY_ADDR,
                       "IRQ_ENTRY_ADDR set before reset");
        TEST_ASSERT_EQ(kpv_ctrl0_lock_write_read(), 1u, "KPV lock_write set before reset");
        TEST_ASSERT_EQ(kpv_ctrl0_lock_use_read(), 1u, "KPV lock_use set before reset");
        TEST_ASSERT_NE(rom_kmcsr_sram_lock_read(), 0u, "SRAM_LOCK set before reset");

        TEST_SUBTEST_PASS();
        TEST_SUBTEST_START("Phase 0: warm reset via external warm_rst_n");

        /* Advance phase before triggering reset */
        *marker = MARKER_PHASE1;
        __asm__ volatile("fence" ::: "memory");

        /* Ask testbench to pulse warm_rst_n; CPU will restart and run Phase 1 */
        if (!tb_km_warm_reset(5000u)) {
            TEST_FAIL("TB_CMD_KM_WARM_RESET failed to be acknowledged");
        }

        /* Should not reach here — CPU restarted by warm reset */
        TEST_FAIL("Execution continued after warm reset from external input");

    } else if (phase == MARKER_PHASE1) {
        /*====================================================================
         * Phase 1: after warm reset from external warm_rst_n
         *====================================================================*/
        TEST_SUBTEST_START("Phase 1: SRAM marker persists across warm-from-external");
        TEST_ASSERT_EQ(*marker, MARKER_PHASE1, "SRAM marker after warm-from-external");
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 1: warm-resettable state cleared");
        verify_warm_resettable_cleared();
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START(
            "Phase 1: COLD_BOOT_DONE persists (ROM re-set, warm reset did not clear)");
        TEST_ASSERT_EQ(tb_cold_boot_done_read(), 1u, "COLD_BOOT_DONE after warm-from-external");
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 1: program warm-resettable state before soft reset");
        set_warm_resettable_state();
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 1: warm reset via SOFT_RST_CODE");

        /* Advance phase before triggering reset */
        *marker = MARKER_PHASE2;
        __asm__ volatile("fence" ::: "memory");

        /* Write magic code to trigger soft warm reset.
         * SOFT_RST_CODE is itself warm-resettable, so it clears on the resulting
         * warm reset — no infinite loop. */
        volatile uint32_t *soft_rst =
            (volatile uint32_t *)KEY_MANAGER_KMCSR_SOFT_RST_CODE_BASE_ADDR;
        *soft_rst = SOFT_RST_CODE_MAGIC;

        /* Should not reach here — CPU restarted by warm reset from SOFT_RST_CODE */
        TEST_FAIL("Execution continued after soft reset write");

    } else if (phase == MARKER_PHASE2) {
        /*====================================================================
         * Phase 2: after warm reset from SOFT_RST_CODE
         *====================================================================*/
        TEST_SUBTEST_START("Phase 2: SRAM marker persists across warm-from-soft");
        TEST_ASSERT_EQ(*marker, MARKER_PHASE2, "SRAM marker after warm-from-soft");
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 2: warm-resettable state cleared after soft reset");
        verify_warm_resettable_cleared();
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 2: COLD_BOOT_DONE persists after warm-from-soft");
        TEST_ASSERT_EQ(tb_cold_boot_done_read(), 1u, "COLD_BOOT_DONE after warm-from-soft");
        TEST_SUBTEST_PASS();

        TEST_PASS();

    } else {
        /* Unexpected marker value — corrupt SRAM or missing phase */
        TEST_FAIL("Unexpected phase marker: 0x%08X", (unsigned)phase);
    }

    return 0;
}
