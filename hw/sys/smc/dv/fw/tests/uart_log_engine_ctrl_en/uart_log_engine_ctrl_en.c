/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Wrapper UART Enable Test
 *
 * Verifies the UART enable control of UART wrapper 0 from firmware: it resets
 * to disabled, follows writes, keeps its reserved bits at zero even after an
 * all-ones write, and reads back correctly over repeated toggles. The pad-mux
 * output it drives is not visible to firmware; an RTL known-value assertion on
 * that output covers it during this sequence.
 */

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

    // Reserved bits stay zero
    check_eq(read_reg(WRAP0_CTRL_REG) & 0xFFFFFFFEu, 0x0u, "reserved bits set after write 1");

    //--------------------------------------------------------------------------
    // Write 0 → read 0
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG, 0u);
    check_eq(read_reg(WRAP0_CTRL_REG) & 0x1u, 0x0u, "after write 0, UART_EN != 0");

    //--------------------------------------------------------------------------
    // Write all ones — only the enable latches; reserved bits read as zero
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG, 0xFFFFFFFFu);
    check_eq(read_reg(WRAP0_CTRL_REG) & 0x1u, 0x1u, "after write 0xFFFFFFFF, UART_EN != 1");
    check_eq(read_reg(WRAP0_CTRL_REG) & 0xFFFFFFFEu, 0x0u,
             "after write 0xFFFFFFFF, reserved bits not RAZ");

    //--------------------------------------------------------------------------
    // Toggle 10x — every read-back matches the value written
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

    // Leave the UART pads disabled at the end of the test
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_ctrl_en_test done");
    test_pass(0);
}
