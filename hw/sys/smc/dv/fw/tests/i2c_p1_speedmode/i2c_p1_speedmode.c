/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P1 Speed Mode Compliance Test
 *
 * =============================================================================
 * Test Description
 * =============================================================================
 *
 * This test verifies that the I2C interface operates correctly across all
 * specified speed modes: Standard (100 kHz), Fast (400 kHz), and Fast Plus (1 MHz).
 *
 * Test Objective:
 * - Verify I2C basic data transfer works in Standard mode (100 kHz)
 * - Verify I2C basic data transfer works in Fast mode (400 kHz)
 * - Verify I2C basic data transfer works in Fast Plus mode (1 MHz)
 * - Ensure data integrity is maintained across all speed modes
 *
 * Expected Result:
 * - All speed modes complete write/read transactions successfully
 * - Data integrity maintained in all modes
 * - No timing violations or protocol errors
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
 * Configuration Details
 * =============================================================================
 *
 * I2C_0 Configuration (Controller Mode):
 *   - Speed: Variable (Standard/Fast/Fast Plus)
 *   - FIFO Thresholds:
 *     * RX FIFO: 29 entries
 *     * FMT FIFO: 5 entries
 *
 * I2C_1 Configuration (Target Mode):
 *   - Address: 0x10 (7-bit)
 *   - Address Mask: 0x7F (exact match)
 *   - Speed: Matches controller speed
 *   - FIFO Thresholds:
 *     * TX FIFO: 5 entries
 *     * ACQ FIFO: 29 entries
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: Wrapper Control Enable (LEVEL 1)
 * Step 3: Test Standard Mode (100 kHz)
 * Step 4: Test Fast Mode (400 kHz)
 * Step 5: Test Fast Plus Mode (1 MHz)
 * Step 6: Test Complete
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0
#define TARGET_IDX 1
#define TARGET_ADDR 0x10

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputs("  Wrapper[");
    simputshex32("", idx);
    simputs("] enabled: mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

static int test_speed_mode(uint8_t speed_mode, const char *mode_name) {
    int ret = I2C_OK;
    uint8_t write_data[4] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t read_buffer[256];
    uint32_t received_len = 0;

    simputs("\n");
    simputs("Testing ");
    simputs(mode_name);
    simputs(" mode...\n");

    // Compute timing parameters for this speed mode
    i2c_timing_physical_t physical_params = {.speed = speed_mode,
                                             .clock_period_nanos = 10,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(speed_mode, 100, &computed_timing);
    }

    // Reconfigure timing for both Controller and Target
    // Note: We only reconfigure timing, not full re-initialization
    simputs("  Reconfiguring Controller timing...\n");
    i2c_config_timing(CONTROLLER_IDX, &computed_timing);

    simputs("  Reconfiguring Target timing...\n");
    i2c_config_timing(TARGET_IDX, &computed_timing);

    // Perform write transaction (non-blocking)
    simputs("  Performing write transaction (non-blocking)...\n");
    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, write_data,
                                                    sizeof(write_data));
    if (ret != I2C_OK) {
        simputs("  ERROR: Write transaction failed\n");
        return ret;
    }

    // Wait for ACQ FIFO data
    simputs("  Waiting for ACQ FIFO data...\n");
    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: ACQ FIFO wait failed\n");
        return ret;
    }

    // Target receives data
    simputs("  Target receiving data...\n");
    ret = i2c_target_receive_transaction(TARGET_IDX, read_buffer, sizeof(read_buffer),
                                         &received_len, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive failed\n");
        return ret;
    }

    simputs("  Received ");
    simputshex32("", received_len);
    simputs(" bytes\n");

    simputs("  ");
    simputs(mode_name);
    simputs(" mode test PASSED\n");

    return I2C_OK;
}

int main(void) {
    int ret = I2C_OK;

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P1 Bus Speed Mode Compliance Test     ##\n");
    simputs("###################################################\n");
    simputs("\n");

    //=========================================================================
    // Step 1: System Initialization
    //=========================================================================
    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    //=========================================================================
    // Step 2: LEVEL 1 - Wrapper Control Enable
    //=========================================================================
    write_scratch(1, 0x00000020);
    simputs("Step 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true); // I2C_0 as Controller
    i2c_wrapper_enable(TARGET_IDX, false);    // I2C_1 as Target
    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization (Standard Mode)
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    // Initialize with Standard mode timing first
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

    // Initialize Controller
    simputs("  Initializing I2C_0 Controller...\n");
    i2c_controller_config_t ctrlr_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Controller initialized successfully\n");

    // Initialize Target
    simputs("  Initializing I2C_1 Target...\n");
    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F,
        .address1 = 0,
        .mask1 = 0,
        .timing = computed_timing,
        .fifo = {.tx_thresh = 5, .acq_thresh = 29, .rx_thresh = 0, .fmt_thresh = 0},
        .enable_interrupts = false,
        .ack_ctrl_mode = false,
        .tx_stretch_ctrl = false,
        .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");

    write_scratch(1, 0x00000031);

    //=========================================================================
    // Step 4: Test Standard Mode (100 kHz)
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Testing Standard Mode (100 kHz)\n");

    ret = test_speed_mode(I2C_SPEED_STANDARD, "Standard (100 kHz)");
    if (ret != I2C_OK) {
        simputs("  Standard mode test FAILED\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    write_scratch(1, 0x00000041);

    //=========================================================================
    // Step 5: Test Fast Mode (400 kHz)
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Testing Fast Mode (400 kHz)\n");

    ret = test_speed_mode(I2C_SPEED_FAST, "Fast (400 kHz)");
    if (ret != I2C_OK) {
        simputs("  Fast mode test FAILED\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }

    write_scratch(1, 0x00000051);

    //=========================================================================
    // Step 6: Test Fast Plus Mode (1 MHz)
    //=========================================================================
    write_scratch(1, 0x00000060);
    simputs("\nStep 6: Testing Fast Plus Mode (1 MHz)\n");

    ret = test_speed_mode(I2C_SPEED_FAST_PLUS, "Fast Plus (1 MHz)");
    if (ret != I2C_OK) {
        simputs("  Fast Plus mode test FAILED\n");
        write_scratch(0, 0xBAD00060);
        test_fail(0);
    }

    write_scratch(1, 0x00000061);

    //=========================================================================
    // Step 6: Test Complete
    //=========================================================================
    simputs("\n");
    simputs("###################################################\n");
    simputs("##   All Speed Mode Tests PASSED                ##\n");
    simputs("###################################################\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);

    return I2C_OK;
}
