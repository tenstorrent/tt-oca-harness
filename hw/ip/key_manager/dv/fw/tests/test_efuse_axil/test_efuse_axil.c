/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_efuse_axil.c
 * @brief OTP/eFuse AXI-Lite crossbar integration test.
 *
 * Exercises the KM CPU -> crossbar (master port 8) -> key_manager.sv remap
 * -> efuse_req_o path and verifies that:
 *   1. Writes to the OTP window (KM-local 0x0001_1xxx) reach the testbench
 *      eFuse responder and read back correctly (positive / OKAY path).
 *   2. The remap is proven by the readback: an un-remapped access would
 *      deliver 0x0001_1xxx to the responder, which decodes only 0x1093_0xxx
 *      and answers SLVERR, so a broken remap fails subtest 1.
 *
 * Sub-regions exercised (using KM-local addresses from key_manager_addr.h):
 *   OTP_EFUSE_MAP  @ KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR  (0x0001_1000, 64-bit
 *                   regwidth; firmware accesses as two consecutive 32-bit words)
 *   OTP_EFUSE_CTRL @ KEY_MANAGER_OTP_EFUSE_CTRL_BASE_ADDR (0x0001_1400, 32-bit)
 *   OTP_EFUSE_MMR  @ KEY_MANAGER_OTP_EFUSE_MMR_BASE_ADDR  (0x0001_1500, 32-bit)
 *
 * Note: The OTP_EFUSE_* registers are declared 'external' in key_manager.rdl,
 * so PeakRDL generates address constants only (no _reg_u struct types).
 * test_read32/test_write32 are therefore used for the whole-word accesses here.
 *
 * The testbench eFuse responder (in tb_key_manager.sv) is a 256-word RAM
 * indexed by addr[11:2] of the remapped address.  Writes are stored and
 * read back, so write-then-read verification confirms the full path.
 *
 * Run with:
 *   make run_fw FW_TEST=test_efuse_axil
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h" /* OTP_EFUSE_*_REG_MAP_BASE_ADDR, per-register _REG_ADDR */
#include "rom_defs.h"         /* ROM_KM_OTP_BASE */

/* Test patterns */
static const uint32_t MAP_PAT_LO = 0xA5A50001u;
static const uint32_t MAP_PAT_HI = 0x5A5A0002u;
static const uint32_t CTRL_PAT = 0xDEADBEEFu;
static const uint32_t MMR_PAT = 0xCAFEBABEu;

int main(void) {
    TEST_INIT();

    if (!tb_set_timeout(50000)) {
        TEST_FAIL("timeout setup failed");
    }

    /* ------------------------------------------------------------------
     * Subtest 1: MAP sub-region (offset +0x000, 64-bit row = two 32-bit words)
     * KEY_MANAGER_OTP_EFUSE_MAP_LOCKS_BASE_ADDR is the first register in the MAP region.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("OTP MAP write-read (LOCKS register, 32-bit low word)");
    test_write32(KEY_MANAGER_OTP_EFUSE_MAP_LOCKS_BASE_ADDR, MAP_PAT_LO);
    {
        uint32_t rd = test_read32(KEY_MANAGER_OTP_EFUSE_MAP_LOCKS_BASE_ADDR);
        TEST_ASSERT_EQ(rd, MAP_PAT_LO, "MAP LOCKS low-word readback");
    }
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("OTP MAP write-read (LOCKS register, 32-bit high word)");
    test_write32(KEY_MANAGER_OTP_EFUSE_MAP_LOCKS_BASE_ADDR + 4u, MAP_PAT_HI);
    {
        uint32_t rd = test_read32(KEY_MANAGER_OTP_EFUSE_MAP_LOCKS_BASE_ADDR + 4u);
        TEST_ASSERT_EQ(rd, MAP_PAT_HI, "MAP LOCKS high-word readback");
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 2: CTRL sub-region (offset +0x400, 32-bit registers)
     * Use KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR as a writable target.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("OTP CTRL write-read (PROGRAM_CTRL register)");
    test_write32(KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR, CTRL_PAT);
    {
        uint32_t rd = test_read32(KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(rd, CTRL_PAT, "CTRL PROGRAM_CTRL readback");
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 3: MMR sub-region (offset +0x500, 32-bit registers)
     * Use KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0) as a writable target.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("OTP MMR write-read (RMA_SIP_TOKEN_I_0 register)");
    test_write32(KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0), MMR_PAT);
    {
        uint32_t rd = test_read32(KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0));
        TEST_ASSERT_EQ(rd, MMR_PAT, "MMR RMA_SIP_TOKEN_I_0 readback");
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 4: ROM_KM_OTP_BASE constant is consistent with the generated
     *            KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR address constant.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("ROM_KM_OTP_BASE matches KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR");
    if (ROM_KM_OTP_BASE != KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR) {
        TEST_FAIL("ROM_KM_OTP_BASE (0x%08X) != KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR (0x%08X)",
                  (unsigned)ROM_KM_OTP_BASE, (unsigned)KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR);
    }
    TEST_SUBTEST_PASS();

    /* ------------------------------------------------------------------
     * Subtest 5: Verify multiple writes reach different responder cells.
     *            Write a second distinct pattern to CTRL+8 then re-read
     *            CTRL+4 to confirm the first write was not corrupted.
     * ------------------------------------------------------------------ */
    TEST_SUBTEST_START("OTP CTRL cell independence (no aliasing)");
    test_write32(KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_READ_CTRL_BASE_ADDR, 0x12345678u);
    {
        uint32_t rd_prog = test_read32(KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR);
        uint32_t rd_read = test_read32(KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_READ_CTRL_BASE_ADDR);
        TEST_ASSERT_EQ(rd_prog, CTRL_PAT, "CTRL PROGRAM_CTRL unchanged");
        TEST_ASSERT_EQ(rd_read, 0x12345678u, "CTRL READ_CTRL new value");
    }
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
