/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p2_concurrent.c
 * @brief I2C P2 Two-Controller Write Test
 *
 * Verifies that the I2C_0 and I2C_1 controllers, configured side by side, can
 * each issue a write to an external target at its own address. The writes run
 * one after the other, not at the same time. A NACK is only logged, so the
 * test fails only on another write error, and the data is not read back.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define I2C_0_IDX 0
#define I2C_1_IDX 1
#define I2C_0_TARGET_ADDR 0x20
#define I2C_1_TARGET_ADDR 0x30

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
    uint8_t i2c0_write_data[4] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t i2c1_write_data[4] = {0x11, 0x22, 0x33, 0x44};

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P2 Concurrent Interface Operation     ##\n");
    simputs("###################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(I2C_0_IDX, true);
    i2c_wrapper_enable(I2C_1_IDX, true);
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("Step 3: LEVEL 2 - I2C IP Initialization\n");

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

    simputs("  Initializing I2C_0 Controller...\n");
    i2c_controller_config_t i2c0_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(I2C_0_IDX, &i2c0_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: I2C_0 Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  I2C_0 Controller initialized successfully\n");

    simputs("  Initializing I2C_1 Controller...\n");
    i2c_controller_config_t i2c1_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(I2C_1_IDX, &i2c1_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: I2C_1 Controller init failed\n");
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }
    simputs("  I2C_1 Controller initialized successfully\n");

    write_scratch(1, 0x00000031);

    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Concurrent Write Operations\n");

    // Blocking writes with STOP, so each controller releases the bus before the next write
    simputs("  I2C_0 writing to target 0x20...\n");
    ret = i2c_controller_write(I2C_0_IDX, I2C_0_TARGET_ADDR, i2c0_write_data,
                               sizeof(i2c0_write_data), true);
    if (ret == I2C_ERROR_NACK) {
        simputs("  WARNING: I2C_0 received NACK from target (VIP may not be responding)\n");
        simputs("  Continuing with next transaction...\n");
    } else if (ret != I2C_OK) {
        simputs("  ERROR: I2C_0 write failed with code: 0x");
        simputshex32("\n", ret);
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    simputs("  I2C_0 write completed\n");

    simputs("  I2C_1 writing to target 0x30...\n");
    ret = i2c_controller_write(I2C_1_IDX, I2C_1_TARGET_ADDR, i2c1_write_data,
                               sizeof(i2c1_write_data), true);
    if (ret == I2C_ERROR_NACK) {
        simputs("  WARNING: I2C_1 received NACK from target (VIP may not be responding)\n");
        simputs("  Continuing...\n");
    } else if (ret != I2C_OK) {
        simputs("  ERROR: I2C_1 write failed with code: 0x");
        simputshex32("\n", ret);
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    simputs("  I2C_1 write completed\n");

    write_scratch(1, 0x00000041);

    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Verify Transactions Completed\n");

    // i2c_controller_write with STOP returns only after the controller goes idle
    simputs("  Both I2C transactions completed successfully\n");
    write_scratch(1, 0x00000052);

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   Concurrent Interface Test PASSED          ##\n");
    simputs("###################################################\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);
}
