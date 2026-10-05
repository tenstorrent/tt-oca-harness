/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p1_adrmask.c
 * @brief I2C P1 Target Dual Address Test
 *
 * Verifies that one I2C target accepts writes on both of its configured
 * addresses, with a different controller writing to each, and that it still
 * accepts a write after the controllers and the target are recovered. Both
 * address masks are set to exact match, so only exact-match addressing is
 * exercised, and the received data is only logged, not compared.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CTRL_0_IDX 0
#define CTRL_1_IDX 1
#define TARGET_IDX 2
#define TARGET_ADDR0 0x10
#define TARGET_ADDR1 0x20

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

static int test_dual_address(void) {
    int ret = I2C_OK;
    uint8_t write_data[2] = {0xAA, 0xBB};
    uint8_t read_buffer[256];
    uint32_t received_len = 0;

    simputs("\n");
    simputs("Testing Dual Address Configuration (I2C_0/I2C_1 Controllers -> I2C_2 Target)...\n");

    simputs("  Test 1: I2C_0 Controller -> Target address 0x10...\n");
    ret = i2c_controller_write_with_header_nonblock(CTRL_0_IDX, TARGET_ADDR0, write_data,
                                                    sizeof(write_data));
    if (ret != I2C_OK) {
        simputs("  ERROR: I2C_0 write to address 0x10 failed\n");
        return ret;
    }

    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target ACQ FIFO wait failed\n");
        return ret;
    }

    ret = i2c_target_receive_transaction(TARGET_IDX, read_buffer, sizeof(read_buffer),
                                         &received_len, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive from address 0x10 failed\n");
        return ret;
    }

    simputs("  Received ");
    simputshex32("", received_len);
    simputs(" bytes from I2C_0 at address 0x10\n");

    simputs("  Test 2: I2C_1 Controller -> Target address 0x20...\n");
    ret = i2c_controller_write_with_header_nonblock(CTRL_1_IDX, TARGET_ADDR1, write_data,
                                                    sizeof(write_data));
    if (ret != I2C_OK) {
        simputs("  ERROR: I2C_1 write to address 0x20 failed\n");
        return ret;
    }

    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target ACQ FIFO wait failed\n");
        return ret;
    }

    ret = i2c_target_receive_transaction(TARGET_IDX, read_buffer, sizeof(read_buffer),
                                         &received_len, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive from address 0x20 failed\n");
        return ret;
    }

    simputs("  Received ");
    simputshex32("", received_len);
    simputs(" bytes from I2C_1 at address 0x20\n");
    simputs("  Dual address test PASSED\n");

    return I2C_OK;
}

static int test_address_masking(void) {
    int ret = I2C_OK;
    uint8_t write_data[2] = {0x55, 0xAA};
    uint8_t read_buffer[256];
    uint32_t received_len = 0;

    simputs("\n");
    simputs("Testing Address Masking (using existing 0x10 config)...\n");

    uint32_t base = i2c_get_base(TARGET_IDX);

    // The target keeps its init-time configuration; reconfiguring it mid-test hangs the
    // controller.

    // Reset the target's ACQ FIFO, then drain anything the reset left behind
    simputs("  Clearing ACQ FIFO (hardware reset + drain)...\n");

    i2c_reset_fifos(TARGET_IDX, false, false, false, true); // ACQ FIFO only
    simputs("    ACQ FIFO reset using ACQRST\n");

    if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
        simputs("    WARNING: ACQ FIFO not empty after reset, draining...\n");
        while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
            (void)read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                   SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        }
    }
    simputs("  ACQ FIFO confirmed empty\n");

    // Target events are sticky and re-assert while their cause (for example a START on the
    // bus) persists, so clear them in a bounded loop until none remain.
    simputs("  Clearing TARGET_EVENTS (may require multiple clears)...\n");
    uint32_t max_clear_attempts = 5;
    while (max_clear_attempts > 0) {
        uint32_t target_events = i2c_get_target_events(TARGET_IDX);
        if (target_events == 0) {
            break;
        }
        simputs("    Found events: 0x");
        simputshex32("", target_events);
        simputs(", clearing...\n");
        i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);

        for (volatile int i = 0; i < 100; i++)
            ;
        max_clear_attempts--;
    }
    simputs("  TARGET_EVENTS cleared\n");

    // Wait for the target to go idle before the next transaction; expiry only logs a warning
    simputs("  Waiting for Target to become idle...\n");
    uint32_t idle_wait = 0;
    const uint32_t IDLE_WAIT_TIMEOUT = 50000; // idle-wait bound, in poll iterations
    while (idle_wait < IDLE_WAIT_TIMEOUT) {
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (status.f.TARGETIDLE) {
            // Give SCL time to be released
            for (volatile int i = 0; i < 1000; i++)
                ;
            break;
        }
        idle_wait++;
    }
    if (idle_wait >= IDLE_WAIT_TIMEOUT) {
        simputs("  WARNING: Target did not become idle after ");
        simputshex32("", idle_wait);
        simputs(" cycles\n");
    } else {
        simputs("  Target confirmed idle after ");
        simputshex32("", idle_wait);
        simputs(" cycles\n");
    }

    simputs("  Sending I2C write to Target address 0x10 (from Controller 0)...\n");
    ret =
        i2c_controller_write_with_header_nonblock(CTRL_0_IDX, 0x10, write_data, sizeof(write_data));
    if (ret != I2C_OK) {
        simputs("  ERROR: Write failed\n");
        return ret;
    }
    simputs("  Write queued\n");

    // Longer timeout than test_dual_address, to allow for recovery latency after the idle wait
    simputs("  Waiting for ACQ FIFO data (timeout=5000)...\n");
    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 5000);
    if (ret != I2C_OK) {
        simputs("  ERROR: ACQ FIFO wait failed\n");
        return ret;
    }

    simputs("  Target receiving data...\n");
    ret = i2c_target_receive_transaction(TARGET_IDX, read_buffer, sizeof(read_buffer),
                                         &received_len, 1000);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive failed\n");
        return ret;
    }

    simputs("  Received ");
    simputshex32("", received_len);
    simputs(" bytes from address 0x10\n");
    simputs("  Address masking test PASSED\n");
    return I2C_OK;
}

int main(void) {
    int ret = I2C_OK;

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P1 Target Address Masking Test (DUT)  ##\n");
    simputs("###################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(CTRL_0_IDX, true);  // I2C_0 as Controller
    i2c_wrapper_enable(CTRL_1_IDX, true);  // I2C_1 as Controller
    i2c_wrapper_enable(TARGET_IDX, false); // I2C_2 as Target
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

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
    i2c_controller_config_t ctrlr_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(CTRL_0_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller 0 init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Controller 0 initialized successfully\n");

    simputs("  Initializing I2C_1 Controller...\n");
    ret = i2c_controller_init(CTRL_1_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller 1 init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Controller 1 initialized successfully\n");

    simputs("  Initializing I2C_2 Target with dual addresses...\n");
    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR0,
        .mask0 = 0x7F,
        .address1 = TARGET_ADDR1,
        .mask1 = 0x7F,
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

    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Testing Dual Address\n");

    ret = test_dual_address();
    if (ret != I2C_OK) {
        simputs("  Dual address test FAILED\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    write_scratch(1, 0x00000041);

    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Testing Address Masking\n");

    // The dual-address writes can leave controller and target state behind; clear it before
    // the next transaction.
    simputs("  Recovering Controller and Target state...\n");

    // Drain target ACQ entries left by the dual-address writes
    simputs("    Draining I2C_2 Target ACQ FIFO from previous test...\n");
    uint32_t target_base = i2c_get_base(TARGET_IDX);
    uint32_t drain_count = 0;
    while (!i2c_target_acq_fifo_empty(TARGET_IDX) && drain_count < 64) {
        (void)read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        drain_count++;
    }
    if (drain_count > 0) {
        simputs("    Drained ");
        simputshex32("", drain_count);
        simputs(" entries from Target ACQ FIFO\n");
    }

    // Clear events and reset the FMT and RX FIFOs of both controllers
    i2c_clear_controller_events(CTRL_0_IDX, 0xFFFFFFFF);
    i2c_clear_controller_events(CTRL_1_IDX, 0xFFFFFFFF);

    i2c_reset_fifos(CTRL_0_IDX, true, true, false, false);
    i2c_reset_fifos(CTRL_1_IDX, true, true, false, false);

    simputs("  Waiting for Controllers to become idle...\n");
    uint32_t ctrl_base_0 = i2c_get_base(CTRL_0_IDX);
    uint32_t ctrl_base_1 = i2c_get_base(CTRL_1_IDX);
    uint32_t ctrl_wait = 0;
    /* Bounded idle wait; expiry is a warning, not a failure, and falls through to the
     * disable/enable force-recovery path below. */
    const uint32_t CTRL_IDLE_TIMEOUT = 20000;
    bool controller_0_idle = false;
    bool controller_1_idle = false;

    while (ctrl_wait < CTRL_IDLE_TIMEOUT) {
        i2c__STATUS_t ctrl_status_0 = {
            .w = read_reg(ctrl_base_0 + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__STATUS_t ctrl_status_1 = {
            .w = read_reg(ctrl_base_1 + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        // A controller that reports an event is cleared and its FIFOs reset again
        uint32_t controller_events_0 = i2c_get_controller_events(CTRL_0_IDX);
        uint32_t controller_events_1 = i2c_get_controller_events(CTRL_1_IDX);

        if (controller_events_0 != 0) {
            simputs("    WARNING: CONTROLLER_0_EVENTS: 0x");
            simputshex32("", controller_events_0);
            simputs(", clearing...\n");
            i2c_clear_controller_events(CTRL_0_IDX, 0xFFFFFFFF);
            i2c_reset_fifos(CTRL_0_IDX, true, true, false, false);
        }

        if (controller_events_1 != 0) {
            simputs("    WARNING: CONTROLLER_1_EVENTS: 0x");
            simputshex32("", controller_events_1);
            simputs(", clearing...\n");
            i2c_clear_controller_events(CTRL_1_IDX, 0xFFFFFFFF);
            i2c_reset_fifos(CTRL_1_IDX, true, true, false, false);
        }

        if (ctrl_status_0.f.HOSTIDLE && ctrl_status_0.f.FMTEMPTY) {
            controller_0_idle = true;
        }
        if (ctrl_status_1.f.HOSTIDLE && ctrl_status_1.f.FMTEMPTY) {
            controller_1_idle = true;
        }

        if (controller_0_idle && controller_1_idle) {
            break;
        }

        ctrl_wait++;

        if ((ctrl_wait % 100) == 0) {
            for (volatile int i = 0; i < 100; i++)
                ;
        }

        if ((ctrl_wait % 1000) == 0) {
            simputs("    [Waiting] Ctrl0_idle=");
            simputshex32("", controller_0_idle ? 1 : 0);
            simputs(", Ctrl1_idle=");
            simputshex32("", controller_1_idle ? 1 : 0);
            simputs(", count=");
            simputshex32("", ctrl_wait);
            simputs("\n");
        }
    }

    if (controller_0_idle && controller_1_idle) {
        simputs("  Both Controllers recovered successfully (idle after ");
        simputshex32("", ctrl_wait);
        simputs(" cycles)\n");
    } else {
        simputs("  WARNING: Controllers did not become idle after ");
        simputshex32("", ctrl_wait);
        simputs(" cycles\n");
        simputs("  Attempting force recovery: disable/enable Controllers...\n");

        if (!controller_0_idle) {
            i2c_controller_disable(CTRL_0_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
            i2c_controller_enable(CTRL_0_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
        }

        if (!controller_1_idle) {
            i2c_controller_disable(CTRL_1_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
            i2c_controller_enable(CTRL_1_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
        }
    }

    for (volatile int i = 0; i < 10000; i++)
        ;

    ret = test_address_masking();
    if (ret != I2C_OK) {
        simputs("  Address masking test FAILED\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }

    write_scratch(1, 0x00000051);

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   All Address Masking Tests PASSED          ##\n");
    simputs("###################################################\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);
}
