/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_decode_err_test
//
// Verify wrapper axi_lite_demux + prim_axi_lite_err_slv behavior on undefined
// CSR addresses inside uart_log_engine_wrap_0. RTL configures the err slave to
// return RESP_DECERR with RDATA = 0x_BADCAB1E. On the SMC CPU side, an
// AXI4-Lite DECERR on a load returns the bus-data value directly (no fault),
// so we read several gap addresses and confirm they all return 0x_BADCAB1E.
//
// SCOPE NOTE: only wrapper-level gap addresses (between sub-regions
// CTRL/UART/LOG_ENGINE) route to the wrapper's `axi_lite_demux ->
// prim_axi_lite_err_slv` and produce DECERR + 0xBADCAB1E. Addresses INSIDE a
// sub-region's address range (e.g. 0xC000A220 between INTR_TEST and
// LOG_CTRL_0) go to the PeakRDL-generated reg block, which is configured with
// `decoded_err = '0` and returns OKAY+0 for undecoded offsets. Those are NOT
// tested here.
//
// Failures call test_fail(0) (noreturn); raise_error + end_test is not reliable
// under -flto with static inline helpers.

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
        test_fail(0); // noreturn
    }
}

static void check_valid_read_no_decerr(uint32_t addr) {
    uint32_t got = read_reg(addr);
    if (got == BADCAB1E) {
        info_msg_s(0, "FAIL: valid addr unexpectedly returned 0xBADCAB1E");
        info_msg_hex32_s(0, "  addr=", addr);
        test_fail(0); // noreturn
    }
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_decode_err_test start");

    // Disable wrapper CTRL and Log Engine to keep TB quiet
    write_reg(WRAP0_CTRL_REG, 0u);
    write_reg(WRAP0_LE_BASE, 0u);

    //--------------------------------------------------------------------------
    // Wrapper-level gap addresses (between sub-regions). These ARE routed to
    // the wrapper's axi_lite_demux + prim_axi_lite_err_slv → DECERR.
    //
    // Layout per uart_log_engine_wrap.rdl:
    //   CTRL_REG_MAP @ 0x000  (size 0x004 — one register)
    //   UART_REG_MAP @ 0x100  (size 0x028 — RBR..ITR)
    //   LOG_ENGINE   @ 0x200  (size 0x080 — CTRL..LOG_CTRL_15 at +0x7C)
    //--------------------------------------------------------------------------
    check_decerr_read(WRAP0_CTRL_REG + 0x004u); // just past CTRL register
    check_decerr_read(WRAP0_CTRL_REG + 0x0FCu); // just below UART base
    check_decerr_read(WRAP0_CTRL_REG + 0x140u); // just past UART region end (0x128)
    check_decerr_read(WRAP0_CTRL_REG + 0x1FCu); // just below LOG_ENGINE base

    //--------------------------------------------------------------------------
    // Sanity: adjacent valid addresses still decode normally (no DECERR).
    //--------------------------------------------------------------------------
    check_valid_read_no_decerr(WRAP0_CTRL_REG);          // CTRL reg
    check_valid_read_no_decerr(WRAP0_UART_BASE + 0x0Cu); // UART LCR
    check_valid_read_no_decerr(WRAP0_LE_BASE);           // LE CTRL
    check_valid_read_no_decerr(WRAP0_LE_BASE + 0x40u);   // LE LOG_CTRL_0
    check_valid_read_no_decerr(WRAP0_LE_BASE + 0x7Cu);   // LE LOG_CTRL_15

    //--------------------------------------------------------------------------
    // Write-side DECERR — confirm writes to gap addresses complete (no bus
    // hang) and surrounding valid addresses still RW.
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
    test_pass(0); // noreturn

    while (1) __asm__("wfi");
    return 0;
}
