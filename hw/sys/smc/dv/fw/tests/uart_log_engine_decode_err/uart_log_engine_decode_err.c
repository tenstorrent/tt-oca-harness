/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Wrapper Decode Error Test
 *
 * Verifies that reads from the address gaps between the control, UART and
 * log-engine regions of UART wrapper 0 return the wrapper's decode-error data
 * pattern, that adjacent valid registers do not, and that writes to gaps
 * complete and leave a valid register writable. A decode error on a CPU load
 * returns the bus data without a fault, so each gap read returns the pattern.
 * Undecoded offsets inside a region are served by that region's register
 * block and are not tested.
 */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define BADCAB1E 0x0BADCAB1Eu

static void check_decerr_read(uint32_t addr) {
    uint32_t got = read_reg(addr);
    if (got != BADCAB1E) {
        info_msg_s(0, "FAIL: decerr read missing 0xBADCAB1E");
        info_msg_hex32_s(0, "  addr=", addr);
        info_msg_hex32_s(0, "  got =", got);
        test_fail(0);
    }
}

static void check_valid_read_no_decerr(uint32_t addr) {
    uint32_t got = read_reg(addr);
    if (got == BADCAB1E) {
        info_msg_s(0, "FAIL: valid addr unexpectedly returned 0xBADCAB1E");
        info_msg_hex32_s(0, "  addr=", addr);
        test_fail(0);
    }
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_decode_err_test start");

    // Keep the UART and the log engine idle
    write_reg(WRAP0_CTRL_REG, 0u);
    write_reg(WRAP0_LE_BASE, 0u);

    //--------------------------------------------------------------------------
    // Gaps between the wrapper's sub-regions reach its decode-error responder.
    //--------------------------------------------------------------------------
    check_decerr_read(WRAP0_CTRL_REG + 0x004u); // just past the control register
    check_decerr_read(WRAP0_CTRL_REG + 0x0FCu); // just below the UART region
    check_decerr_read(WRAP0_CTRL_REG + 0x140u); // past the end of the UART region
    check_decerr_read(WRAP0_CTRL_REG + 0x1FCu); // just below the log-engine region

    //--------------------------------------------------------------------------
    // Sanity: adjacent valid addresses still decode normally (no DECERR).
    //--------------------------------------------------------------------------
    check_valid_read_no_decerr(WRAP0_CTRL_REG);          // CTRL reg
    check_valid_read_no_decerr(WRAP0_UART_BASE + 0x0Cu); // UART LCR
    check_valid_read_no_decerr(WRAP0_LE_BASE);           // LE CTRL
    check_valid_read_no_decerr(WRAP0_LE_BASE + 0x40u);   // LE LOG_CTRL_0
    check_valid_read_no_decerr(WRAP0_LE_BASE + 0x7Cu);   // LE LOG_CTRL_15

    //--------------------------------------------------------------------------
    // Writes to gap addresses complete without a bus hang, and a valid register
    // still reads back what is written.
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG + 0x008u, 0xDEADBEEFu);
    write_reg(WRAP0_CTRL_REG + 0x150u, 0x12345678u);

    write_reg(WRAP0_CTRL_REG, 0x1u);
    if ((read_reg(WRAP0_CTRL_REG) & 0x1u) != 1u) {
        info_msg_s(0, "FAIL: CTRL.UART_EN unrecoverable after DECERR writes");
        test_fail(0);
    }
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_decode_err_test done");
    test_pass(0);
}
