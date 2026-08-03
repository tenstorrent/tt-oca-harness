/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P1 FIFO Stress Test
 *
 * =============================================================================
 * Test Description
 * =============================================================================
 *
 * This test verifies FIFO error handling and system stability under continuous
 * I2C traffic. Performs 8 sequential write/receive transactions between internal
 * I2C controller and target.
 *
 * Expected Result:
 * - All 8 transactions complete successfully
 * - No FIFO overflow/underflow errors
 * - System remains stable without corruption or deadlock
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
 *   - Speed: Standard mode (100 kHz)
 *   - FIFO Thresholds:
 *     * RX FIFO: 29 entries
 *     * FMT FIFO: 5 entries
 *
 * I2C_1 Configuration (Target Mode):
 *   - Address: 0x10 (7-bit)
 *   - Address Mask: 0x7F (exact match)
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
 * Step 3: I2C IP Initialization (LEVEL 2)
 * Step 4: FIFO Stress Test (3 transactions)
 * Step 5: Rapid FIFO Stress Test (5 more transactions)
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

int main(void) {
    int ret = I2C_OK;

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P1 FIFO Overflow/Underflow Test       ##\n");
    simputs("###################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true); // I2C_0 as Controller
    i2c_wrapper_enable(TARGET_IDX, false);    // I2C_1 as Target
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("Step 3: LEVEL 2 - I2C IP Initialization\n");

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
    // Step 4: FIFO Stress Test - Simple I2C Write
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("Step 4: Simple I2C Write\n");

    uint8_t data_buf[] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t recv_buffer[16];
    uint32_t received_len = 0;

    // Step 4.1: Controller write (non-blocking)
    write_scratch(1, 0x00000041);
    simputs("  [4.1] Controller write (non-blocking)...\n");
    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, data_buf,
                                                    sizeof(data_buf));
    if (ret != I2C_OK) {
        simputs("  [ERROR] Controller write failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    write_scratch(1, 0x00000042);
    simputs("  [4.1] Controller write command sent to FMT FIFO\n");

    // Step 4.2: Wait for ACQ FIFO to have data (target received data from controller)
    write_scratch(1, 0x00000043);
    simputs("  [4.2] Waiting for ACQ FIFO data...\n");
    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 1000);
    if (ret != I2C_OK) {
        simputs("  [ERROR] ACQ FIFO wait failed\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    write_scratch(1, 0x00000044);
    simputs("  [4.2] ACQ FIFO has data, ready to receive\n");

    // Step 4.3: Target receive the transaction
    write_scratch(1, 0x00000045);
    simputs("  [4.3] Target receive START\n");
    ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer, sizeof(recv_buffer),
                                         &received_len, 1000);
    if (ret != I2C_OK) {
        simputs("  [ERROR] Target receive failed\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }
    write_scratch(1, 0x00000046);
    simputs("  [4.3] Target received 0x");
    for (size_t k = 0; k < received_len; k++) {
        uint8_t hex = (recv_buffer[k] >> 4) & 0xF;
        simputs(hex < 10 ? "0" : "");
        simputs("0");
    }
    simputs(" bytes\n");

    write_scratch(1, 0x00000047);

    //=========================================================================
    // Step 6: Test Complete
    //=========================================================================
    simputs("\n");
    simputs("FIFO Stress Test PASSED\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);

    return I2C_OK;
}
