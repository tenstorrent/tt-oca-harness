/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C Read Test - Simple Controller Read Transaction
 *
 * =============================================================================
 * Test Purpose
 * =============================================================================
 *
 * This test verifies I2C Controller read transaction:
 *   - I2C_0 configured as Controller mode
 *   - Controller reads from target address 0x5a
 *   - Testbench verifies GPIO toggle and decodes START, address (0x5a5a), STOP
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
 *   - Handles timing, FIFO, interrupts, transactions
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: LEVEL 1 - Wrapper Control Enable (I2C_0 as Controller)
 * Step 3: LEVEL 2 - I2C IP Initialization (I2C_0 Controller)
 * Step 4: Controller Read Transaction (target address 0x5a)
 *
 * =============================================================================
 * Transaction Format
 * =============================================================================
 *
 * Read Transaction:
 *   [START] [Target Addr: 0xB5 (0x5a << 1 | 0x1)] [ACK/NAK] [STOP]
 *
 * Note: Address 0x5a5a interpreted as target address 0x5a (7-bit)
 *       Testbench should decode GPIO signals to verify:
 *       - START condition
 *       - Address: 0x5a5a (or 0x5a as 7-bit)
 *       - STOP condition
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
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t CONTROLLER_IDX = 0; // I2C_0 as Controller
    const uint8_t TARGET_ADDR = 0x5a;  // Target address (7-bit) - from 0x5a5a
    int ret;

    //-------------//
    // RESET & PLL //
    //-------------//

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C Read Test                        ##\n");
    simputs("##      Controller Read Address 0x5a        ##\n");
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
    //=========================================================================
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

    // Enable I2C_0 as Controller mode
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    // Initialize I2C_0 as Controller
    simputs("  Initializing I2C_0 Controller...\n");

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

    i2c_controller_config_t ctrlr_cfg = {.timing = computed_timing,
                                         .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH,
                                                  .fmt_thresh = I2C_DEFAULT_FMT_THRESH,
                                                  .tx_thresh = 0,
                                                  .acq_thresh = 0},
                                         .enable_interrupts = false,
                                         .timeout_cycles = 0};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Controller initialized successfully\n");

    write_scratch(1, 0x00000031);

    //=========================================================================
    // Step 4: Controller Read Transaction
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Controller Read Transaction\n");

    simputs("  Reading from target address 0x");
    simputshex32("", TARGET_ADDR);
    simputs("\n");
    simputs("  Expected I2C transaction on GPIO:\n");
    simputs("    - START condition\n");
    simputs("    - Address: 0x");
    simputshex32("", TARGET_ADDR);
    simputs(" (7-bit) = 0x");
    simputshex32("", (TARGET_ADDR << 1) | 0x1);
    simputs(" (I2C format with read bit)\n");
    simputs("    - STOP condition\n");
    simputs("  Testbench should verify GPIO toggle and decode transaction\n");

    /*
     * GPIO-toggle leaf: only I2C_0 is armed; no Target peer. NACK is the
     * expected completion — the TB checks SCL/SDA START/addr/STOP, not data.
     * Do not fail-closed on NACK here; that needs an ACK peer (see i2c_sanity).
     */
    unsigned char read_buffer[1];
    ret = i2c_controller_read(CONTROLLER_IDX, TARGET_ADDR, read_buffer, sizeof(read_buffer), true);
    if (ret != I2C_OK) {
        if (ret == I2C_ERROR_NACK) {
            simputs("  NOTE: NACK received (expected - no Target configured)\n");
            simputs("  GPIO toggle verification: START + address 0x");
            simputshex32("", TARGET_ADDR);
            simputs(" + read bit was transmitted\n");
        } else {
            simputs("  ERROR: Controller read failed with error code: 0x");
            simputshex32("", ret);
            simputs("\n");
            write_scratch(0, 0xBAD00040);
            test_fail(0);
        }
    } else {
        simputs("  Read transaction completed\n");
        simputs("  Received data byte: 0x");
        simputshex32("", read_buffer[0]);
        simputs("\n");
    }

    write_scratch(1, 0x00000041);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    write_scratch(1, 0x00000090);

    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputs("  - I2C_0 (Controller): @ 0xC0009000\n");
    simputs("  - Target Address:     0x");
    simputshex32("", TARGET_ADDR);
    simputs(" (7-bit)\n");
    simputs("  - GPIO Signals:       GPIO[37]=SCL, GPIO[38]=SDA\n");
    simputs("  - Transaction:        START + Address(0x");
    simputshex32("", TARGET_ADDR);
    simputs(") + STOP\n");
    simputs("  - Testbench Verify:   GPIO toggle, decode START/STOP, address 0x5a5a\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
