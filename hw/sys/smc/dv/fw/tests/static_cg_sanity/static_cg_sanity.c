/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

// Phase completion signals
#define TEST_COMPLETE_PHASE1    0xC0FFEE  // Clock gating enabled
#define COCOTB_PROCEED_SIGNAL   0x77777777
#define TEST_COMPLETE_PHASE2    0xDECAFE  // Clock gating disabled

int main(void) {
    // Signal firmware ready
    write_scratch(5, 0x55555555);

    // Enable all peripheral clock gating simultaneously (static and dynamic)
    smc_base_config__CLOCK_GATE_CONTROL_t clock_gate_ctrl;

    // Enable static clock gaters (peripheral clocks)
    clock_gate_ctrl.f.avs_cg_en = 0x1;
    clock_gate_ctrl.f.i2c_cg_en = 0x1;
    clock_gate_ctrl.f.uart_cg_en = 0x1;
    clock_gate_ctrl.f.telemetry_cg_en = 0x1;
    clock_gate_ctrl.f.cg_hysteresis = 0x2e;

    write_reg(SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR, clock_gate_ctrl.w);

    // Clocks should now be gated
    write_scratch(5, TEST_COMPLETE_PHASE1);

    // Wait for cocotb test to signal to proceed to phase 2
    uint32_t cocotb_signal = 0;
    while (cocotb_signal != COCOTB_PROCEED_SIGNAL) {
        cocotb_signal = read_scratch(6);
    }

    // Disable all peripheral clock gating (static and dynamic)
    clock_gate_ctrl.w = 0;  // Clear all clock gating enables
    write_reg(SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR, clock_gate_ctrl.w);

    write_scratch(5, TEST_COMPLETE_PHASE2);

    // Pass the test
    test_pass(0);

    // Wait forever
    while (1) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {
    return main();
}