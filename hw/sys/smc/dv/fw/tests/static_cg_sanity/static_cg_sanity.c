/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

// Scratch handshake values shared with the TB
#define TEST_COMPLETE_PHASE1 0xC0FFEE // Clock gating enabled
#define COCOTB_PROCEED_SIGNAL 0x77777777
#define TEST_COMPLETE_PHASE2 0xDECAFE // Clock gating disabled

/* The TB half that answers the proceed handshake may be absent from a run, so
 * the wait is bounded and expiry is a failure.
 */
#define PROCEED_BOUND 200000u

#define ERR_NO_PROCEED 0xBAD00C61u
#define ERR_GATE_READBACK 0xBAD00C62u
#define ERR_UNGATE_READBACK 0xBAD00C63u

static void fail_cg(uint32_t code, const char *msg) {
    write_scratch(0, code);
    simputs("  ERROR: ");
    simputs(msg);
    simputs("\n");
    test_fail(0);
}

/* The clock gate control is plain read/write storage, so a written word must
 * read back bit for bit.
 */
static void check_gate_ctrl(uint32_t wrote, uint32_t code, const char *msg) {
    uint32_t got = read_reg(SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR);

    if (got != wrote) {
        info_msg_hex32_s(0, "  wrote: ", wrote);
        info_msg_hex32_s(0, "  read : ", got);
        fail_cg(code, msg);
    }
}

int main(void) {
    // Signal firmware ready
    write_scratch(5, 0x55555555);

    // Enable the static peripheral clock gaters together
    smc_base_config__CLOCK_GATE_CONTROL_t clock_gate_ctrl;

    clock_gate_ctrl.f.avs_cg_en = 0x1;
    clock_gate_ctrl.f.i2c_cg_en = 0x1;
    clock_gate_ctrl.f.uart_cg_en = 0x1;
    clock_gate_ctrl.f.telemetry_cg_en = 0x1;
    clock_gate_ctrl.f.cg_hysteresis = 0x2e;

    write_reg(SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR, clock_gate_ctrl.w);
    check_gate_ctrl(clock_gate_ctrl.w, ERR_GATE_READBACK,
                    "CLOCK_GATE_CONTROL did not hold the gate-enable word");

    // Tell the TB that clock gating is enabled
    write_scratch(5, TEST_COMPLETE_PHASE1);

    // Wait, bounded, for the TB to signal phase 2
    uint32_t cocotb_signal = 0;
    uint32_t i;

    for (i = 0; i < PROCEED_BOUND; i++) {
        cocotb_signal = read_scratch(6);
        if (cocotb_signal == COCOTB_PROCEED_SIGNAL) {
            break;
        }
    }
    if (i == PROCEED_BOUND) {
        info_msg_hex32_s(0, "  last scratch[6]: ", cocotb_signal);
        fail_cg(ERR_NO_PROCEED, "TB never wrote the phase-2 proceed signal to scratch[6]");
    }

    // Disable all clock gating
    clock_gate_ctrl.w = 0;
    write_reg(SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR, clock_gate_ctrl.w);
    check_gate_ctrl(0u, ERR_UNGATE_READBACK,
                    "CLOCK_GATE_CONTROL did not clear on the ungate write");

    write_scratch(5, TEST_COMPLETE_PHASE2);

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    /* Only hart 0 drives the sequence: four harts in main() would race on the
     * same CLOCK_GATE_CONTROL word and poll the same scratch handshake. */
    if (metal_cpu_get_current_hartid() != 0) {
        while (1) {
            __asm__("wfi");
        }
    }

    return main();
}
