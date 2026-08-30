/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_km_exec_sram_locked_ok.c
 * @brief Positive-path test: instruction fetch from write-locked SRAM in SRAM mode.
 *
 * With SRAM_EXEC_MODE.enable == 1 and the target region write-locked, instruction
 * fetch from that SRAM region is whitelisted and must succeed without fault.
 * Verifies the positive execution path: code copied to locked SRAM executes
 * correctly and reports success.
 *
 * That same fetch is what engages the ROM lockout, so this test doubles as the
 * arm/engage check: the ROM is readable up to the fetch and unreadable after it.
 *
 * Run with:
 *   make run_fw FW_TEST=test_km_exec_sram_locked_ok
 */

#include "test_common.h"
#include "rom_boot.h"
#include "rom_kmcsr.h"
#include "rom_picorv32.h"
#include "key_manager_fw.h"

/* A ROM word that holds real code in every link mode: the IRQ vector at 0x10 is
 * in physical ROM even in the default execute-from-VROM build, so it is both
 * non-zero and parity-valid.  Most of the ROM is uninitialized in that build. */
#define ROM_LIVE_WORD_ADDR (ROM_KM_ROM_BASE + 0x10u)

/* Use region 8 (0x8000 + 8*0x400 = 0xA000) as the locked code region. ROM .data,
 * .bss and the stack all sit in the top of SRAM (the stack descends from .data
 * no further than __km_fw_load_limit), so a low region is the only place where
 * write-locking cannot freeze live ROM state. No mutable firmware is loaded in
 * this test, so the load area below the stack floor is free scratch. */
#define LOCKED_CODE_REGION 8u
#define REGION_SIZE_BYTES SRAM_LOCK_REGION_BYTES
#define SRAM_CODE_BASE (SRAM_BASE + (LOCKED_CODE_REGION * REGION_SIZE_BYTES))

/* The copied function will add a constant to its argument. */
#define ADD_CONSTANT 0x5A5A0001u

typedef uint32_t (*add_fn_t)(uint32_t);

__attribute__((noinline)) static uint32_t locked_add_stub(uint32_t x) {
    return x + ADD_CONSTANT;
}
__attribute__((noinline)) static void locked_add_stub_end(void) {
    __asm__ volatile("");
}

int rom_boot_wipe_enabled(void) {
    return 0;
}
int rom_unrec_wipe_enabled(void) {
    return 0;
}

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(500000) || !tb_drbg_set_seed(0xFA12u, 5000)) {
        TEST_FAIL("TB setup failed");
    }

    rom_boot_init(); /* enables exec_violation_en */

    /* Copy function to SRAM region 8 *before* locking (data write, allowed). */
    TEST_SUBTEST_START("copy function to SRAM region 8");
    uint32_t fn_size = (uint32_t)((uintptr_t)locked_add_stub_end - (uintptr_t)locked_add_stub);
    if (fn_size == 0 || fn_size > REGION_SIZE_BYTES) {
        TEST_FAIL("Unexpected function size");
    }
    uint8_t *src = (uint8_t *)(uintptr_t)locked_add_stub;
    uint8_t *dst = (uint8_t *)SRAM_CODE_BASE;
    for (uint32_t i = 0; i < fn_size; i++) dst[i] = src[i];
    TEST_SUBTEST_PASS();

    /* Write-lock region 8.  After this, data writes to 0xA000-0xA3FF are
     * blocked and the region is whitelisted for instruction fetch in SRAM mode. */
    TEST_SUBTEST_START("write-lock region 8");
    rom_kmcsr_sram_lock_set(1u << LOCKED_CODE_REGION);
    TEST_ASSERT_EQ((rom_kmcsr_sram_lock_read() >> LOCKED_CODE_REGION) & 1u, 1u,
                   "SRAM_LOCK bit 8 must be set");
    TEST_SUBTEST_PASS();

    /* Baseline: the ROM is still readable while the lockout is only armed. */
    TEST_SUBTEST_START("ROM readable before the lockout engages");
    volatile uint32_t *rom_word = (volatile uint32_t *)(uintptr_t)ROM_LIVE_WORD_ADDR;
    uint32_t rom_word_live = *rom_word;
    TEST_ASSERT_NE(rom_word_live, 0u, "ROM word must be non-zero while ROM is live");
    TEST_SUBTEST_PASS();

    /* Enable SRAM execution mode.  Write-locked SRAM becomes executable and the
     * ROM lockout is armed; the ROM stays reachable until the fetch below. */
    TEST_SUBTEST_START("enable SRAM execution mode");
    rom_kmcsr_sram_exec_mode_set();
    TEST_ASSERT_EQ(rom_kmcsr_sram_exec_mode_read(), 1u, "EXEC_MODE.enable must be 1");
    TEST_SUBTEST_PASS();

    /* Mask CPU IRQs for the remainder of the test.  Once the lockout engages, the
     * IRQ vector at 0x10 is in the revoked ROM, so any interrupt would fetch
     * zeros and trap instead of running a handler.  This mirrors the real
     * handover, which also masks everything before crossing over.  The violation
     * bits are checked directly below rather than through the ISR. */
    (void)rom_picorv32_maskirq(0xFFFFFFFFu);

    /* Execute from locked SRAM.  This is whitelisted and must succeed — and it is
     * the committed fetch that engages the ROM lockout. */
    TEST_SUBTEST_START("execute from locked SRAM region 8");
    add_fn_t fn = (add_fn_t)SRAM_CODE_BASE;
    volatile uint32_t result = fn(1u);
    TEST_ASSERT_EQ(result, 1u + ADD_CONSTANT, "SRAM function returned correct value");
    TEST_SUBTEST_PASS();

    /* The ROM is now revoked: the same address reads zero rather than the word
     * observed above.  This is a data read, so it raises the violation without
     * trapping. */
    TEST_SUBTEST_START("ROM read blocked after the lockout engages");
    uint32_t rom_word_blocked = *rom_word;
    TEST_ASSERT_EQ(rom_word_blocked, 0u, "blocked ROM read must return zero");
    TEST_SUBTEST_PASS();

    /* The blocked access is reported as a ROM lockout violation, not as a
     * generic execute violation, and the whitelisted SRAM fetch raised nothing. */
    TEST_SUBTEST_START("ROM_ACCESS_VIOLATION reported, EXEC_VIOLATION not");
    km_csr__irq_status_reg_t status = {.w = rom_kmcsr_irq_status_read()};
    TEST_ASSERT_EQ(status.f.rom_access_violation, 1u, "ROM_ACCESS_VIOLATION must be set");
    TEST_ASSERT_EQ(status.f.exec_violation, 0u, "EXEC_VIOLATION must stay clear");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
