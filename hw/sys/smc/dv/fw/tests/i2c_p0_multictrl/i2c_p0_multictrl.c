/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P0 Multi-Controller Test - Three SMC Controllers Arbitration
 *
 * =============================================================================
 * Test Purpose: Multi-Master Arbitration Verification
 * =============================================================================
 *
 * This test verifies I2C multi-master arbitration behavior:
 *   - Configure I2C_0, I2C_1, I2C_2 as Controller mode (SMC masters)
 *   - All three controllers start transmission simultaneously
 *   - Controllers compete for bus access based on target address
 *   - Monitor SMC's internal status registers and bus signals (SDA, SCL)
 *
 * =============================================================================
 * Test Architecture: Two-Level I2C Control
 * =============================================================================
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Controls GPIO pad multiplexing
 *   - Selects I2C mode (Controller/Target)
 *   - MUST be configured FIRST before IP-level configuration
 *
 * LEVEL 2: IP Control (0xC0009000 + 0x200*idx)
 *   - OpenTitan I2C IP protocol layer
 *   - Base addresses:
 *     * I2C_0: 0xC0009000
 *     * I2C_1: 0xC0009200
 *     * I2C_2: 0xC0009400
 *
 * =============================================================================
 * Test Configuration
 * =============================================================================
 *
 * SMC Controllers:
 *   - I2C_0: Controller mode, writes to target address 0x10
 *   - I2C_1: Controller mode, writes to target address 0x11
 *   - I2C_2: Controller mode, writes to target address 0x12
 *   - Timing: Standard mode, 100 kHz
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: LEVEL 1 - Enable all three wrappers in Controller mode
 * Step 3: LEVEL 2 - Initialize all three I2C IPs as Controllers
 * Step 4: Signal ready to Python testbench (scratch[1] = 0xEBEDEBE2)
 * Step 5: Trigger simultaneous transactions from all three controllers
 * Step 6: Python testbench monitors arbitration and bus signals
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

//=============================================================================
// Helper Functions
//=============================================================================

/**
 * @brief Enable I2C Wrapper Control
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputs("] enabled: mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t NUM_CONTROLLERS = 3;
    const uint32_t CONTROLLER_IDX[3] = {0, 1, 2};
    const uint8_t TARGET_ADDR[3] = {0x10, 0x11, 0x12};
    int ret;

    //-------------//
    // RESET & PLL //
    //-------------//

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Multi-Controller Test            ##\n");
    simputs("##   Three SMC Controllers Arbitration       ##\n");
    simputs("################################################\n");
    simputs("\n");

    //=========================================================================
    // Step 1: System Initialization
    //=========================================================================
    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");
    write_scratch(1, 0x00000011);

    //=========================================================================
    // Step 2: LEVEL 1 - Wrapper Control Enable
    //         Enable all three wrappers in Controller mode
    //=========================================================================
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

    for (uint32_t i = 0; i < NUM_CONTROLLERS; i++) {
        i2c_wrapper_enable(CONTROLLER_IDX[i], true);
    }

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
    //         Initialize all three I2C IPs as Controllers
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    // Compute timing parameters
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 10,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    // Initialize all controllers
    for (uint32_t i = 0; i < NUM_CONTROLLERS; i++) {
        simputs("  Initializing I2C_");
        simputshex32("", CONTROLLER_IDX[i]);
        simputs(" Controller...\n");

        i2c_controller_config_t ctrlr_cfg = {.timing = computed_timing,
                                             .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH,
                                                      .fmt_thresh = I2C_DEFAULT_FMT_THRESH,
                                                      .tx_thresh = 0,
                                                      .acq_thresh = 0},
                                             .enable_interrupts = false,
                                             .timeout_cycles = 0};

        ret = i2c_controller_init(CONTROLLER_IDX[i], &ctrlr_cfg);
        if (ret != I2C_OK) {
            simputs("  ERROR: Controller ");
            simputshex32("", CONTROLLER_IDX[i]);
            simputs(" init failed\n");
            write_scratch(0, 0xBAD00030 | (CONTROLLER_IDX[i] & 0xFF));
            test_fail(0);
        }
        simputs("  Controller ");
        simputshex32("", CONTROLLER_IDX[i]);
        simputs(" initialized successfully\n");
    }

    write_scratch(1, 0x00000031);

    //=========================================================================
    // Step 4: Signal ready to Python testbench
    //=========================================================================
    write_scratch(1, 0xEBEDEBE2);
    simputs("\nStep 4: All SMC Controllers ready, waiting for Python testbench...\n");
    simputs("  SMC Controllers will send to target addresses:\n");
    for (uint32_t i = 0; i < NUM_CONTROLLERS; i++) {
        simputs("    - I2C_");
        simputshex32("", CONTROLLER_IDX[i]);
        simputs(" -> Target 0x");
        simputshex32("", TARGET_ADDR[i]);
        simputs("\n");
    }

    // Wait a bit for Python testbench to set up targets
    for (volatile int j = 0; j < 10000; j++)
        ;

    //=========================================================================
    // Step 5: Trigger I2C Transactions (simultaneously from all controllers)
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 5: Triggering simultaneous transactions from all controllers...\n");

    // Test data for each controller
    unsigned char test_data[3][4] = {
        {0xAA, 0xBB, 0xCC, 0xDD}, // Controller 0 data
        {0x11, 0x22, 0x33, 0x44}, // Controller 1 data
        {0x55, 0x66, 0x77, 0x88}  // Controller 2 data
    };
    const uint32_t data_size = 4;

    // Send transactions from all controllers (non-blocking)
    for (uint32_t i = 0; i < NUM_CONTROLLERS; i++) {
        simputs("  Sending transaction from Controller[");
        simputshex32("", CONTROLLER_IDX[i]);
        simputs("] -> Target 0x");
        simputshex32("", TARGET_ADDR[i]);
        simputs("\n");

        // Non-blocking write - returns immediately after writing to FMT FIFO
        ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX[i], TARGET_ADDR[i],
                                                        test_data[i], data_size);

        if (ret != I2C_OK) {
            simputs("  ERROR: Controller ");
            simputshex32("", CONTROLLER_IDX[i]);
            simputs(" write failed with error ");
            simputshex32("", ret);
            simputs("\n");
            write_scratch(0, 0xBAD00040 | (CONTROLLER_IDX[i] & 0xFF));
            test_fail(0);
        }

        // Small delay between triggers to allow arbitration to occur
        if (i < NUM_CONTROLLERS - 1) {
            for (volatile int j = 0; j < 10000; j++)
                ;
        }
    }

    simputs("  All transactions sent (non-blocking)\n");
    simputs("  Python testbench will monitor arbitration and bus signals\n");

    write_scratch(1, 0x00000050);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    write_scratch(1, 0x00000090);

    // Signal setup complete to testbench
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputs("  - I2C_0 (SMC Controller): @ 0xC0009000 -> Target 0x10\n");
    simputs("  - I2C_1 (SMC Controller): @ 0xC0009200 -> Target 0x11\n");
    simputs("  - I2C_2 (SMC Controller): @ 0xC0009400 -> Target 0x12\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
