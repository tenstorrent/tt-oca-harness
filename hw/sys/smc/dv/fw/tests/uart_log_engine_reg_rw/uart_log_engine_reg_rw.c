/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

// smc_uart_log_engine_reg_rw_test
//
// FW-driven register RW walk for the OCAH UART & Log Engine Wrapper on SMC.
// Exercises:
//   - Wrapper-level CTRL register (CTRL.UART_EN)
//   - UART 16550 main register map (DLAB=0): LCR, MCR, SCR, ECR, ITR, IER
//   - UART 16550 main register map (DLAB=1): DLL, DLM
//   - Log Engine register map: CTRL, LOG_REGION_SIZE, LOG_REGION_ADDR_{LO,HI},
//                              LOG_WRITE_ADDR, INTR_ENABLE, LOG_CTRL[0..15]
//   - RO sanity reads on UART LSR/MSR/IIR (constants per RDL)
//
// Test ends via test_pass(0). Mismatches use info_msg_* + test_fail(0)
// (fail-fast). Avoids raise_error_* + end_test pattern which proved
// unreliable under -Os -flto + static inline.
// Coverage maps to UART_LOG_ENGINE_TEST_PLAN smc_uart_log_engine_reg_rw_test
// and UART_LOG_ENGINE_COVERAGE_POINT UART_REG_COV_01 / LE_REG_COV_01 /
// LE_REG_COV_02.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG      SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define UART_RBR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IER_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IIR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LSR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MSR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_SCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_ECR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ECR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_ITR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))

#define LE_CTRL_OFF         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_SIZE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_ADDR_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_WRITE_ADDR_OFF   (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_ENABLE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_TEST_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_TEST_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

// Per-IP wrapper indexes used by SMC; we only walk WRAP_0 to keep simulation
// time bounded.  Additional wrappers are covered by other tests.

#define MASK_1_BIT          0x00000001u
#define MASK_2_BIT          0x00000003u
#define MASK_5_BIT          0x0000001Fu
#define MASK_6_BIT          0x0000003Fu
#define MASK_8_BIT          0x000000FFu
#define MASK_11_BIT_INTR    0x00000011u   // INTR_{STATUS,ENABLE,TEST} bits {4,0}
#define MASK_16_BIT         0x0000FFFFu   // LOG_CTRL[i].LOG_LEN
#define MASK_20_BIT         0x000FFFFFu   // LOG_REGION_SIZE
#define MASK_32_BIT         0xFFFFFFFFu

static const uint32_t PATTERNS[] = {
    0x00000000u,
    0xFFFFFFFFu,
    0xAAAAAAAAu,
    0x55555555u,
    0xDEADBEEFu,
    0xCAFEBABEu,
};
#define NUM_PATTERNS (sizeof(PATTERNS) / sizeof(PATTERNS[0]))

// Walk one RW register: for each pattern, write pattern, read back, expect
// (pattern & valid_mask). The original value is saved and restored.
static void rw_walk_one(uint32_t reg_addr, uint32_t valid_mask, uint32_t info_code) {
    uint32_t saved = read_reg(reg_addr);
    for (uint32_t i = 0; i < NUM_PATTERNS; i++) {
        uint32_t pat = PATTERNS[i];
        write_reg(reg_addr, pat);
        uint32_t got = read_reg(reg_addr);
        uint32_t expected = pat & valid_mask;
        if (got != expected) {
            info_msg(0, info_code);
            info_msg_hex32_s(0, "FAIL: RW mismatch addr=", reg_addr);
            info_msg_hex32_s(0, "  wrote   =", pat);
            info_msg_hex32_s(0, "  expected=", expected);
            info_msg_hex32_s(0, "  got     =", got);
            test_fail(0);
        }
    }
    // Restore original (best effort: only masked bits matter for HW state).
    write_reg(reg_addr, saved);
}

// Read-only register sanity: read twice (no side effect for fields with
// `onread`), compare against expected reset constant under the supplied mask.
static void ro_check(uint32_t reg_addr, uint32_t expect, uint32_t mask, uint32_t info_code) {
    uint32_t got = read_reg(reg_addr) & mask;
    if (got != (expect & mask)) {
        info_msg(0, info_code);
        info_msg_hex32_s(0, "FAIL: RO mismatch addr=", reg_addr);
        info_msg_hex32_s(0, "  expected=", expect & mask);
        info_msg_hex32_s(0, "  got     =", got);
        test_fail(0);
    }
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_reg_rw_test start");

    // Make sure the Log Engine stays disabled for the entire register RW walk
    // (avoids triggering log transfers when LOG_CTRL[i] is written non-zero).
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);

    //--------------------------------------------------------------------------
    // 1. Wrapper CTRL.UART_EN (1 bit)
    //--------------------------------------------------------------------------
    info_msg_s(0, "wrapper CTRL");
    rw_walk_one(WRAP0_CTRL_REG, MASK_1_BIT, 0x100001);
    // Leave UART disabled at the pad-mux level when test ends.
    write_reg(WRAP0_CTRL_REG, 0u);

    //--------------------------------------------------------------------------
    // 2. UART 16550 main register map (DLAB=0)
    //    - Ensure DLAB=0 before walking RBR/IER addresses for non-DLAB regs.
    //--------------------------------------------------------------------------
    info_msg_s(0, "UART DLAB=0 walk");

    // Force LCR.DLAB = 0 first so other reg accesses don't hit DLL/DLM.
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0u);

    // LCR — full 8 bits per RDL.  Restore to DLAB=0 at the end.
    rw_walk_one(WRAP0_UART_BASE + UART_LCR_OFF, MASK_8_BIT, 0x100100);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0u);

    // MCR — 6 bits per RDL (DTR/RTS/OUT1/OUT2/LOOP/LINE_LOOPBACK).
    rw_walk_one(WRAP0_UART_BASE + UART_MCR_OFF, MASK_6_BIT, 0x100101);

    // SCR — 8 bits, hw=na (pure software scratch).
    rw_walk_one(WRAP0_UART_BASE + UART_SCR_OFF, MASK_8_BIT, 0x100102);

    // ECR — 2 bits (RCVR_TRIGGER_MS2B[1:0]).
    rw_walk_one(WRAP0_UART_BASE + UART_ECR_OFF, MASK_2_BIT, 0x100103);

    // ITR — 6 bits (TRBFI/TTBEI/TLSI/TDSSI/TFEI/TRTI).
    rw_walk_one(WRAP0_UART_BASE + UART_ITR_OFF, MASK_6_BIT, 0x100104);

    // Restore MCR/SCR/ECR/ITR.  rw_walk_one already restored each.

    // IER (DLAB=0) — 5 bits.  Make sure DLAB=0 before walking IER.
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0u);
    rw_walk_one(WRAP0_UART_BASE + UART_IER_OFF, MASK_5_BIT, 0x100105);

    //--------------------------------------------------------------------------
    // 3. RO sanity reads (DLAB=0): LSR, MSR, IIR
    //--------------------------------------------------------------------------
    info_msg_s(0, "UART RO sanity");

    // LSR reset: THRE=1, TEMT=1 → 0x60.  Mask off level/intr bits that may have
    // been toggled by previous writes; check only THRE/TEMT.
    ro_check(WRAP0_UART_BASE + UART_LSR_OFF, 0x60u, 0x60u, 0x100110);

    // IIR.INTERRUPT_PENDING is active-low and 1 on reset → bit[0]=1.
    ro_check(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u, 0x01u, 0x100111);

    // MSR has no documented reset constant under a fixed input pattern; just
    // confirm the read returns a value with no X (any read completes -> OK).
    (void)read_reg(WRAP0_UART_BASE + UART_MSR_OFF);

    //--------------------------------------------------------------------------
    // 4. UART 16550 (DLAB=1): DLL @ RBR_OFF, DLM @ IER_OFF
    //--------------------------------------------------------------------------
    info_msg_s(0, "UART DLAB=1 walk");

    // Set DLAB=1.  Write the LCR with DLAB=1 only (other LCR fields = 0).
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);

    rw_walk_one(WRAP0_UART_BASE + UART_RBR_OFF, MASK_8_BIT, 0x100120);  // DLL
    rw_walk_one(WRAP0_UART_BASE + UART_IER_OFF, MASK_8_BIT, 0x100121);  // DLM

    // Restore DLAB=0 so the rest of the regs map normally.
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0u);

    //--------------------------------------------------------------------------
    // 5. Log Engine registers (CTRL.EN held low for the entire walk)
    //--------------------------------------------------------------------------
    info_msg_s(0, "log_engine walk");

    // CTRL.EN is bit[0].  rw_walk_one restores the original (=0) after.
    rw_walk_one(WRAP0_LE_BASE + LE_CTRL_OFF,        MASK_1_BIT,  0x100200);

    // LOG_REGION_SIZE — 20 bits.
    rw_walk_one(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, MASK_20_BIT, 0x100201);

    // LOG_REGION_ADDR is a 64-bit register accessed as two 32-bit words.
    // RDL: offset+0 → LO, offset+4 → HI.  Both 32 valid bits.
    rw_walk_one(WRAP0_LE_BASE + LE_REGION_ADDR_OFF,        MASK_32_BIT, 0x100202);  // LO
    rw_walk_one(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4,    MASK_32_BIT, 0x100203);  // HI

    // LOG_WRITE_ADDR — full 32 bits.
    rw_walk_one(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF,  MASK_32_BIT, 0x100204);

    // INTR_ENABLE — only bits {4,0} are defined.
    rw_walk_one(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, MASK_11_BIT_INTR, 0x100205);

    // LOG_CTRL[0..15] — only verify address decodes (read=0 at reset).
    // We deliberately do NOT walk patterns here: writing a nonzero value
    // raises an arbiter request, and writing the next pattern drops it
    // before the arbiter can grant — that violates
    // `prim_arbiter_tree.ReqStaysHighUntilGranted0_M` (SVA). The arbiter's
    // `req_chk_i` is not gated by CTRL.EN in the current wrapper, so even
    // with engine disabled the check fires. The actual RW path for
    // LOG_CTRL[i] is exercised legally (with full request-grant handshake)
    // by smc_uart_log_engine_single_entry_test / _region_size_test.
    for (uint32_t i = 0; i < 16; i++) {
        uint32_t v = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF + (i * 4)) & MASK_16_BIT;
        if (v != 0u) {
            info_msg(0, 0x100210 + i);
            info_msg_hex32_s(0, "FAIL: LOG_CTRL[i] not 0 at reset, i=", i);
            info_msg_hex32_s(0, "  read=", v);
            test_fail(0);
        }
    }

    // Sanity: re-read INTR_STATUS — must be 0 (no error injected this test).
    ro_check(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x0u, MASK_11_BIT_INTR, 0x100230);

    //--------------------------------------------------------------------------
    // Done
    //--------------------------------------------------------------------------
    info_msg_s(0, "smc_uart_log_engine_reg_rw_test done");

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
    return 0;
}
