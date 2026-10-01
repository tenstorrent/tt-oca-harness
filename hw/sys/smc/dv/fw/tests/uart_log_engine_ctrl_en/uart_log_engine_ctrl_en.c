/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_ctrl_en_test
//
// Exercise the wrapper-level CTRL.UART_EN bit (offset 0 of the
// uart_log_engine_ctrl region). FW verifies the CSR-side behavior:
//   * Reset default = 0
//   * Write 1 → read-back 1
//   * Write 0 → read-back 0
//   * Toggle N times: read-backs match writes
//   * Reserved bits [31:1] stay 0
//
// The pad-mux side-effect (uart_en_o) is not visible from FW. The wrapper's
// `ASSERT_KNOWN(UartEnKnownO_A, uart_en_o)` SVA fires if the output ever
// becomes X during this sequence.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)

static void check_eq(uint32_t got, uint32_t expect, const char *name) {
    if (got != expect) {
        info_msg_s(0, "FAIL:");
        info_msg_s(0, name);
        info_msg_hex32_s(0, "  expected=", expect);
        info_msg_hex32_s(0, "  got     =", got);
        test_fail(0);
    }
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_ctrl_en_test start");

    //--------------------------------------------------------------------------
    // Reset default
    //--------------------------------------------------------------------------
    check_eq(read_reg(WRAP0_CTRL_REG) & 0xFFFFFFFFu, 0x0u, "reset default != 0");

    //--------------------------------------------------------------------------
    // Write 1 → read 1
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG, 1u);
    check_eq(read_reg(WRAP0_CTRL_REG) & 0x1u, 0x1u, "after write 1, UART_EN != 1");

    // Reserved bits should remain 0
    check_eq(read_reg(WRAP0_CTRL_REG) & 0xFFFFFFFEu, 0x0u, "reserved bits set after write 1");

    //--------------------------------------------------------------------------
    // Write 0 → read 0
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG, 0u);
    check_eq(read_reg(WRAP0_CTRL_REG) & 0x1u, 0x0u, "after write 0, UART_EN != 0");

    //--------------------------------------------------------------------------
    // Write a value with reserved bits set (0xFFFFFFFF) — only UART_EN
    // (bit 0) should latch, reserved bits drop.
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG, 0xFFFFFFFFu);
    check_eq(read_reg(WRAP0_CTRL_REG) & 0x1u, 0x1u, "after write 0xFFFFFFFF, UART_EN != 1");
    check_eq(read_reg(WRAP0_CTRL_REG) & 0xFFFFFFFEu, 0x0u,
             "after write 0xFFFFFFFF, reserved bits not RAZ");

    //--------------------------------------------------------------------------
    // Toggle 10x — observe no spurious transitions in read-back
    //--------------------------------------------------------------------------
    for (int i = 0; i < 10; i++) {
        uint32_t v = (uint32_t)(i & 1);
        write_reg(WRAP0_CTRL_REG, v);
        if ((read_reg(WRAP0_CTRL_REG) & 0x1u) != v) {
            info_msg_s(0, "FAIL: toggle read-back mismatch");
            info_msg_hex32_s(0, "  iter =", (uint32_t)i);
            info_msg_hex32_s(0, "  wrote=", v);
            test_fail(0);
        }
    }

    // Leave UART disabled at the pad-mux level at end of test
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_ctrl_en_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
