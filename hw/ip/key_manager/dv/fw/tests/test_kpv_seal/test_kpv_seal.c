/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_kpv_seal.c
 * @brief A sealed KPV slot can be revoked but never reused
 *
 * A slot with seal set is sealed, and hardware holds lock_write set alongside
 * it.  Sealing is what lets firmware running after handover trust the material
 * a slot holds: a write-locked slot on its own proves nothing, because an erase
 * clears lock_write and frees the slot to be rewritten and re-locked.  A seal
 * leaves the erase available but changes its outcome: the slot is retired
 * rather than freed, so the material can be destroyed while the slot itself
 * stays out of circulation.
 *
 * Phase 0 (cold boot) establishes both halves of that:
 *   - A single seal write sets lock_write in hardware; a key-data write then
 *     raises SLVERR and the data survives.
 *   - The erase proceeds and retires the slot: lock_write held, lock_use set,
 *     seal still set, and both writes and reads answer SLVERR afterwards.
 *   - Re-erasing a retired slot changes nothing, and an unsealed neighbour
 *     still erases to a fully cleared, reusable slot.
 *
 * Phase 1 (after warm reset) establishes the two ways out:
 *   - Warm reset clears the lock bits, returning the slot to the ROM.  The
 *     data it reveals is not what was sealed, which is how the retiring erase
 *     is shown to have destroyed it.
 *   - A wipe releases a sealed slot outright, zeroing data and every lock.
 *
 * Run with:
 *   make run_fw FW_TEST=test_kpv_seal
 */

#include "test_common.h"
#include "irq_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"
#include "rom_kpv.h"
#include "rom_drbg.h"
#include "rom_defs.h"
#include "rom_kmcsr.h"

/* Phase marker: must be below BSS_START so crt0.s does not clear it on warm
 * restart.  Use a distinct offset from other multi-phase tests. */
#define MARKER_ADDR (SRAM_BASE + 0x2000u)
#define MARKER_PHASE1 0x5EA10001u

/* Sealed slot and its neighbour, which stays unsealed as the control. */
#define SEALED_SLOT 7u
#define UNSEALED_SLOT 8u

/* Phase 0 and phase 1 key patterns, distinct so a stale word is recognisable. */
#define KEY_BASE_P0 0x5EA10000u
#define KEY_BASE_P1 0x5EA11100u

/* Value the refused writes attempt to leave in the sealed slot. */
#define FORGED_WORD 0x0BAD0BADu

/* Erasing a slot walks its 16 words; the phases erase three times over and
 * also wait out a warm reset and a wipe. */
#define TEST_TIMEOUT_CYCLES 400000u

/**
 * SLVERR only sets a sticky status bit and the access still retires, so the
 * probes below survive while the fault enables stay clear.
 */
static int take_slverr(void) {
    km_csr__irq_status_reg_t status;
    int seen;

    status.w = rom_kmcsr_irq_status_read();
    seen = status.f.axi_slverr ? 1 : 0;
    if (seen) {
        km_csr__irq_status_reg_t clear_val = {0};
        clear_val.f.axi_slverr = 1;
        rom_kmcsr_irq_status_clear(clear_val.w);
    }
    return seen;
}

/** CTRL of a sealed slot: the seal plus the write lock hardware sets with it. */
static uint32_t sealed_ctrl(void) {
    km_kpv__ctrl_reg_t ctrl = {0};
    ctrl.f.lock_write = 1;
    ctrl.f.seal = 1;
    return ctrl.w;
}

/** CTRL of a retired slot: a sealed slot that an erase has read-locked. */
static uint32_t retired_ctrl(void) {
    km_kpv__ctrl_reg_t ctrl = {0};
    ctrl.f.lock_write = 1;
    ctrl.f.lock_use = 1;
    ctrl.f.seal = 1;
    return ctrl.w;
}

static void write_key(uint8_t slot, uint32_t base) {
    for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++)
        KPV_KEY_WORD(slot, w) = base | (uint32_t)w;
}

static void verify_key(uint8_t slot, uint32_t base, const char *what) {
    for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t expected = base | (uint32_t)w;
        uint32_t got = KPV_KEY_WORD(slot, w);
        if (got != expected) {
            TEST_FAIL("%s: slot %u word %u is 0x%08X, expected 0x%08X", what, (unsigned)slot,
                      (unsigned)w, (unsigned)got, (unsigned)expected);
        }
    }
}

static void verify_key_changed(uint8_t slot, uint32_t base, const char *what) {
    for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t expected = base | (uint32_t)w;
        uint32_t got = KPV_KEY_WORD(slot, w);
        if (got == expected) {
            TEST_FAIL("%s: slot %u word %u still holds 0x%08X", what, (unsigned)slot, (unsigned)w,
                      (unsigned)got);
        }
    }
}

static void verify_key_zero(uint8_t slot, const char *what) {
    for (uint8_t w = 0; w < ROM_KM_KPV_WORDS_PER_SLOT; w++) {
        uint32_t got = KPV_KEY_WORD(slot, w);
        if (got != 0u) {
            TEST_FAIL("%s: slot %u word %u is 0x%08X, expected zero", what, (unsigned)slot,
                      (unsigned)w, (unsigned)got);
        }
    }
}

/* Raw key data is only inspectable with the scrambler off. */
static void kpv_setup_unscrambled(void) {
    if (!tb_drbg_set_seed(0x5EA1u, 1000)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }
    rom_drbg_init();
    rom_kpv_init_scrambler();
    rom_kpv_scrambler_disable();
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(TEST_TIMEOUT_CYCLES)) {
        TEST_FAIL("Failed to set testbench timeout");
    }

    volatile uint32_t *marker = (volatile uint32_t *)MARKER_ADDR;
    uint32_t phase = *marker;

    if (phase == 0u) {
        kpv_setup_unscrambled();

        {
            km_csr__irq_enable_reg_t enable;
            enable.w = rom_kmcsr_irq_enable_read();
            TEST_ASSERT(!enable.f.axi_slverr_en,
                        "the AXI SLVERR IRQ enable must be clear so the refused writes below are "
                        "observed rather than fatal (IRQ_ENABLE=0x%08X)",
                        (unsigned)enable.w);
            TEST_ASSERT(!take_slverr(), "the SLVERR status bit must be clear at test start");
        }

        TEST_SUBTEST_START("Phase 0: sealing a slot write-locks it in hardware");
        write_key(SEALED_SLOT, KEY_BASE_P0);
        write_key(UNSEALED_SLOT, KEY_BASE_P0);
        verify_key(SEALED_SLOT, KEY_BASE_P0, "written key");

        if (rom_kpv_seal_slot(SEALED_SLOT) != 0) {
            TEST_FAIL("seal of slot %u did not take (CTRL=0x%08X)", (unsigned)SEALED_SLOT,
                      (unsigned)KPV_CTRL(SEALED_SLOT).w);
        }
        TEST_ASSERT(KPV_CTRL(SEALED_SLOT).w == sealed_ctrl(),
                    "the seal alone must leave slot %u CTRL at 0x%08X, not 0x%08X",
                    (unsigned)SEALED_SLOT, (unsigned)sealed_ctrl(),
                    (unsigned)KPV_CTRL(SEALED_SLOT).w);
        TEST_ASSERT(rom_kpv_slot_sealed(SEALED_SLOT), "slot %u must report sealed",
                    (unsigned)SEALED_SLOT);
        TEST_ASSERT(!rom_kpv_slot_retired(SEALED_SLOT),
                    "slot %u must not report retired before it is erased", (unsigned)SEALED_SLOT);
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: a sealed slot refuses a key write");
        KPV_KEY_WORD(SEALED_SLOT, 0) = FORGED_WORD;
        TEST_ASSERT(take_slverr(), "a key write to sealed slot %u must answer SLVERR",
                    (unsigned)SEALED_SLOT);
        verify_key(SEALED_SLOT, KEY_BASE_P0, "key after refused write");
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: erasing a sealed slot retires it");
        rom_kpv_erase_slot(SEALED_SLOT);
        TEST_ASSERT(KPV_CTRL(SEALED_SLOT).w == retired_ctrl(),
                    "the erase must leave slot %u CTRL at 0x%08X, not 0x%08X",
                    (unsigned)SEALED_SLOT, (unsigned)retired_ctrl(),
                    (unsigned)KPV_CTRL(SEALED_SLOT).w);
        TEST_ASSERT(rom_kpv_slot_retired(SEALED_SLOT), "slot %u must report retired",
                    (unsigned)SEALED_SLOT);
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: a retired slot answers neither writes nor reads");
        KPV_KEY_WORD(SEALED_SLOT, 0) = FORGED_WORD;
        TEST_ASSERT(take_slverr(), "a key write to retired slot %u must answer SLVERR",
                    (unsigned)SEALED_SLOT);
        {
            uint32_t got = KPV_KEY_WORD(SEALED_SLOT, 0);
            TEST_ASSERT(take_slverr(), "a key read of retired slot %u must answer SLVERR",
                        (unsigned)SEALED_SLOT);
            TEST_ASSERT(got == 0u, "a key read of retired slot %u must return zero, not 0x%08X",
                        (unsigned)SEALED_SLOT, (unsigned)got);
        }
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: re-erasing a retired slot changes nothing");
        rom_kpv_erase_slot(SEALED_SLOT);
        TEST_ASSERT(KPV_CTRL(SEALED_SLOT).w == retired_ctrl(),
                    "the second erase must leave slot %u CTRL at 0x%08X, not 0x%08X",
                    (unsigned)SEALED_SLOT, (unsigned)retired_ctrl(),
                    (unsigned)KPV_CTRL(SEALED_SLOT).w);
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: an unsealed neighbour still erases free");
        rom_kpv_erase_slot(UNSEALED_SLOT);
        verify_key_changed(UNSEALED_SLOT, KEY_BASE_P0, "key after erase");
        TEST_ASSERT(KPV_CTRL(UNSEALED_SLOT).w == 0u, "the erase must clear slot %u CTRL (0x%08X)",
                    (unsigned)UNSEALED_SLOT, (unsigned)KPV_CTRL(UNSEALED_SLOT).w);
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 0: warm reset");
        *marker = MARKER_PHASE1;
        __asm__ volatile("fence" ::: "memory");

        if (!tb_km_warm_reset(5000u)) {
            TEST_FAIL("TB_CMD_KM_WARM_RESET not acknowledged");
        }
        TEST_FAIL("Execution continued after warm reset");

    } else if (phase == MARKER_PHASE1) {
        kpv_setup_unscrambled();

        TEST_SUBTEST_START("Phase 1: warm reset releases a retired slot");
        TEST_ASSERT(KPV_CTRL(SEALED_SLOT).w == 0u,
                    "the warm reset must clear slot %u CTRL (0x%08X)", (unsigned)SEALED_SLOT,
                    (unsigned)KPV_CTRL(SEALED_SLOT).w);
        verify_key_changed(SEALED_SLOT, KEY_BASE_P0, "key the retiring erase destroyed");
        TEST_SUBTEST_PASS();

        TEST_SUBTEST_START("Phase 1: a wipe releases a sealed slot");
        write_key(SEALED_SLOT, KEY_BASE_P1);
        verify_key(SEALED_SLOT, KEY_BASE_P1, "rewritten key");
        if (rom_kpv_seal_slot(SEALED_SLOT) != 0) {
            TEST_FAIL("re-seal of slot %u did not take (CTRL=0x%08X)", (unsigned)SEALED_SLOT,
                      (unsigned)KPV_CTRL(SEALED_SLOT).w);
        }

        if (!tb_wipe_trigger(10000u)) {
            TEST_FAIL("TB_CMD_WIPE_TRIGGER failed");
        }

        verify_key_zero(SEALED_SLOT, "key after wipe");
        TEST_ASSERT(KPV_CTRL(SEALED_SLOT).w == 0u,
                    "the wipe must clear every lock bit of slot %u (CTRL=0x%08X)",
                    (unsigned)SEALED_SLOT, (unsigned)KPV_CTRL(SEALED_SLOT).w);
        TEST_SUBTEST_PASS();

        TEST_PASS();

    } else {
        TEST_FAIL("Unexpected phase marker: 0x%08X", (unsigned)phase);
    }

    return 0;
}
