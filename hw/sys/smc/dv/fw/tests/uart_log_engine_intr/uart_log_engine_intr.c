/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_intr_test
//
// Verify Log Engine interrupt machinery. Per RTL (log_engine.sv, "Interrupt
// Registers"):
//   reg_in.INTR_STATUS.<bit>.next = real_err || INTR_TEST.<bit>
//   irq_o = |(INTR_STATUS & INTR_ENABLE)
//
// INTR_ENABLE masks the interrupt output only; INTR_STATUS latches whether or
// not the interrupt is enabled and is cleared only by W1C, so an event that
// arrives while masked is not lost. This test covers the four cells of the
// truth table (real_err is held 0 here — no AXI error injected):
//
//   ENABLE  INTR_TEST   →  INTR_STATUS
//   ─────────────────────────────────────
//     0       0         →     0
//     0       1 (pulse) →     1   (latches even while masked)
//     1       0         →     0
//     1       1 (pulse) →     1   (latches, W1C to clear)
//
// Also verifies that INTR_TEST is `singlepulse` (reads back 0 after write).
// Tested for both LOG_FETCH_ERR (bit 0) and LOG_WRITE_ERR (bit 4).

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)
#define LE_INTR_STATUS_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_ENABLE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_TEST_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_TEST_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define BIT_FETCH_ERR (1u << 0)
#define BIT_WRITE_ERR (1u << 4)

static void expect_status(uint32_t expect, uint32_t mask, const char *what) {
    uint32_t got = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & mask;
    if (got != (expect & mask)) {
        info_msg_s(0, "FAIL:");
        info_msg_s(0, what);
        info_msg_hex32_s(0, "  expected status=", expect & mask);
        info_msg_hex32_s(0, "  got status     =", got);
        test_fail(0);
    }
}

static void run_one_bit(uint32_t bit) {
    info_msg_hex32_s(0, "intr_test bit=", bit);

    // Clear any stale status (W1C does not depend on ENABLE)
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, bit);
    expect_status(0u, bit, "precondition: status must be 0 after W1C");

    //----------------------------------------------------------------------
    // Cell (ENABLE=0, INTR_TEST=pulse) — status latches even while masked
    //----------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, bit); // singlepulse
    expect_status(bit, bit, "ENABLE=0 + INTR_TEST pulse: status must latch (not gated)");

    // The masked event is still pending: enabling later must not be needed to
    // see it, and W1C must clear it with ENABLE still 0.
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, bit);
    expect_status(0u, bit, "ENABLE=0 + W1C: status must clear");

    // Confirm INTR_TEST.bit reads back 0 (singlepulse)
    {
        uint32_t tval = read_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF) & bit;
        if (tval != 0u) {
            info_msg_s(0, "FAIL: INTR_TEST not singlepulse");
            info_msg_hex32_s(0, "  bit       =", bit);
            info_msg_hex32_s(0, "  read-back =", tval);
            test_fail(0);
        }
    }

    //----------------------------------------------------------------------
    // Cell (ENABLE=1, INTR_TEST=pulse) — status latches
    //----------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, bit);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, bit);
    expect_status(bit, bit, "ENABLE=1 + INTR_TEST pulse: status must latch");

    // Writing 0 to status must NOT clear (W1C)
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0u);
    expect_status(bit, bit, "writing 0 cleared a W1C bit (must not)");

    // W1C clear
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, bit);
    expect_status(0u, bit, "after W1C: status must be 0");

    //----------------------------------------------------------------------
    // Cell (ENABLE=1, INTR_TEST=0) — status stays 0
    //----------------------------------------------------------------------
    expect_status(0u, bit, "ENABLE=1 + no pulse: status must stay 0");

    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_intr_test start");

    // Engine disabled — we're only exercising INTR machinery via INTR_TEST.
    write_reg(WRAP0_LE_BASE, 0u);

    run_one_bit(BIT_FETCH_ERR);
    run_one_bit(BIT_WRITE_ERR);

    //--------------------------------------------------------------------------
    // Cross test: pulse both bits simultaneously with both enabled
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    expect_status(BIT_FETCH_ERR | BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                  "both pulses (ENABLE=both): status not both set");
    // Selective W1C
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
    expect_status(BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                  "selective W1C: only FETCH_ERR should clear");
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_WRITE_ERR);
    expect_status(0u, BIT_FETCH_ERR | BIT_WRITE_ERR, "after both cleared: status not 0");

    //--------------------------------------------------------------------------
    // Mixed enables: ENABLE=FETCH only, pulse both → both latch (ENABLE masks
    // the interrupt line, not the status)
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    expect_status(BIT_FETCH_ERR | BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                  "ENABLE=FETCH only: both bits must still latch");
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);

    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);

    info_msg_s(0, "smc_uart_log_engine_intr_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
