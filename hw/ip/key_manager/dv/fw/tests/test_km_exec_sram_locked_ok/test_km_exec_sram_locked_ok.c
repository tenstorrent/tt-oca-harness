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
 * Run with:
 *   make run_fw FW_TEST=test_km_exec_sram_locked_ok
 */

#include "test_common.h"
#include "rom_boot.h"
#include "rom_kmcsr.h"
#include "key_manager_fw.h"

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

    /* Enable SRAM execution mode.  ROM and write-locked SRAM become executable. */
    TEST_SUBTEST_START("enable SRAM execution mode");
    rom_kmcsr_sram_exec_mode_set();
    TEST_ASSERT_EQ(rom_kmcsr_sram_exec_mode_read(), 1u, "EXEC_MODE.enable must be 1");
    TEST_SUBTEST_PASS();

    /* Execute from locked SRAM.  This is whitelisted and must succeed. */
    TEST_SUBTEST_START("execute from locked SRAM region 8");
    add_fn_t fn = (add_fn_t)SRAM_CODE_BASE;
    volatile uint32_t result = fn(1u);
    TEST_ASSERT_EQ(result, 1u + ADD_CONSTANT, "SRAM function returned correct value");
    TEST_SUBTEST_PASS();

    /* ROM remains callable in SRAM mode (whitelist includes ROM). */
    TEST_SUBTEST_START("ROM call from SRAM mode succeeds");
    volatile uint32_t version = rom_kmcsr_version_read();
    TEST_ASSERT_NE(version, 0u, "version register must be non-zero");
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
