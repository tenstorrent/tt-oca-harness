/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Interrupt Status, Enable and Test
 *
 * Verifies that each log engine error status bit (fetch error and write error)
 * latches on an interrupt-test pulse whether or not its interrupt is enabled,
 * clears only when software writes 1 to it, and clears independently of the
 * other bit, and that the interrupt-test register reads back 0. The engine
 * stays disabled, so no real bus error is raised; the interrupt output itself
 * is not observed.
 */

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

    // Clearing does not depend on the enable
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, bit);
    expect_status(0u, bit, "precondition: status must be 0 after W1C");

    //----------------------------------------------------------------------
    // Masked: a test pulse still latches the status bit
    //----------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, bit);
    expect_status(bit, bit, "ENABLE=0 + INTR_TEST pulse: status must latch (not gated)");

    // A masked event stays pending and clears without being enabled first
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, bit);
    expect_status(0u, bit, "ENABLE=0 + W1C: status must clear");

    // The test register is a single pulse and reads back 0
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
    // Enabled: a test pulse latches the status bit
    //----------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, bit);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, bit);
    expect_status(bit, bit, "ENABLE=1 + INTR_TEST pulse: status must latch");

    // Only writing 1 clears a status bit
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0u);
    expect_status(bit, bit, "writing 0 cleared a W1C bit (must not)");

    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, bit);
    expect_status(0u, bit, "after W1C: status must be 0");

    //----------------------------------------------------------------------
    // Enabled without a pulse: the status bit stays clear
    //----------------------------------------------------------------------
    expect_status(0u, bit, "ENABLE=1 + no pulse: status must stay 0");

    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_intr_test start");

    // The engine stays disabled so only test pulses can set the status bits
    write_reg(WRAP0_LE_BASE, 0u);

    run_one_bit(BIT_FETCH_ERR);
    run_one_bit(BIT_WRITE_ERR);

    //--------------------------------------------------------------------------
    // Both bits pulsed together latch together and clear independently
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    expect_status(BIT_FETCH_ERR | BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                  "both pulses (ENABLE=both): status not both set");
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
    expect_status(BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                  "selective W1C: only FETCH_ERR should clear");
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_WRITE_ERR);
    expect_status(0u, BIT_FETCH_ERR | BIT_WRITE_ERR, "after both cleared: status not 0");

    //--------------------------------------------------------------------------
    // The enable masks the interrupt output, not the status
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    expect_status(BIT_FETCH_ERR | BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                  "ENABLE=FETCH only: both bits must still latch");
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);

    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);

    info_msg_s(0, "smc_uart_log_engine_intr_test done");
    test_pass(0);
}
