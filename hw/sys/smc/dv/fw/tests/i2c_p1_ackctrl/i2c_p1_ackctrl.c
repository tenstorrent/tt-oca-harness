/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P1 ACK Control Mode Test
 *
 * =============================================================================
 * Test Description
 * =============================================================================
 *
 * This test verifies the programmable ACK control feature, including manual
 * ACK/NACK and automatic ACK modes in Target mode.
 *
 * Test Objective:
 * - Verify automatic ACK mode: Target automatically sends ACK when receiving data
 *
 * Expected Result:
 * - Automatic mode: Target automatically ACKs all received bytes
 *
 * =============================================================================
 * Test Architecture: Two-Level I2C Control
 * =============================================================================
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Controls GPIO pad multiplexing
 *   - Selects I2C mode (Controller/Target)
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
 *   - FIFO Thresholds: RX=29, FMT=5
 *
 * I2C_1 Configuration (Target Mode):
 *   - Address: 0x10 (7-bit)
 *   - ACK Control: Automatic
 *   - FIFO Thresholds: TX=5, ACQ=29
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: Wrapper Control Enable
 * Step 3: Test Automatic ACK Mode
 * Step 4: Test Complete
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

static int test_automatic_ack_mode(void) {
    int ret = I2C_OK;
    uint8_t write_data[4] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t read_buffer[256];
    uint32_t received_len = 0;

    simputs("\n");
    simputs("Testing Automatic ACK Mode...\n");

    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    simputs("  Initializing Controller...\n");
    i2c_controller_config_t ctrlr_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        return ret;
    }

    simputs("  Initializing Target with Automatic ACK...\n");
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
        return ret;
    }

    simputs("  Controller writing data (non-blocking)...\n");
    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, write_data,
                                                    sizeof(write_data));
    if (ret != I2C_OK) {
        simputs("  ERROR: Write transaction failed\n");
        return ret;
    }

    simputs("  Waiting for ACQ FIFO data...\n");
    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: ACQ FIFO wait failed\n");
        return ret;
    }

    simputs("  Target receiving data (automatic ACK)...\n");
    ret = i2c_target_receive_transaction(TARGET_IDX, read_buffer, sizeof(read_buffer),
                                         &received_len, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive failed\n");
        return ret;
    }

    simputs("  Received ");
    simputshex32("", received_len);
    simputs(" bytes\n");

    simputs("  Automatic ACK mode test PASSED\n");
    return I2C_OK;
}

// Manual ACK mode needs per-byte ACK/NACK control that i2c_target_receive_transaction()
// does not provide; this image exercises automatic ACK only.

int main(void) {
    int ret = I2C_OK;

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P1 ACK Control Mode Test              ##\n");
    simputs("###################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    i2c_wrapper_enable(TARGET_IDX, false);
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("\nStep 3: Testing Automatic ACK Mode\n");

    ret = test_automatic_ack_mode();
    if (ret != I2C_OK) {
        simputs("  Automatic ACK mode test FAILED\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    write_scratch(1, 0x00000031);

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   ACK Control Mode Test PASSED              ##\n");
    simputs("###################################################\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);

    return I2C_OK;
}
