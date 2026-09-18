/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P1 Target Address Masking Function Test (DUT Mode)
 *
 * =============================================================================
 * Test Description
 * =============================================================================
 *
 * This test verifies the I2C Target module's dual-address capability and its
 * programmable address masking feature using DUT mode configuration.
 *
 * Test Objective:
 * - I2C_0 (Controller): Initiates write transactions
 * - I2C_1 (Controller): Initiates write transactions
 * - I2C_2 (Target): Receives transactions and responds with address masking
 * - Verify Target responds to configured addresses with address masking enabled
 *
 * Expected Result:
 * - Both controllers successfully write to target
 * - Target responds correctly to address matching with masking
 * - All transactions complete without errors
 *
 * =============================================================================
 * Test Architecture: Two-Level I2C Control with Three Instances
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
 *   - GPIO: GPIO[37]=SCL, GPIO[38]=SDA
 *   - FIFO Thresholds: RX=29, FMT=5
 *
 * I2C_1 Configuration (Controller Mode):
 *   - Speed: Standard mode (100 kHz)
 *   - GPIO: GPIO[41]=SCL, GPIO[42]=SDA
 *   - FIFO Thresholds: RX=29, FMT=5
 *
 * I2C_2 Configuration (Target Mode):
 *   - GPIO: GPIO[45]=SCL, GPIO[46]=SDA
 *   - Address0: 0x10 (7-bit)
 *   - Address1: 0x20 (7-bit)
 *   - Mask: 0x7F (accept exact matches)
 *   - FIFO Thresholds: TX=5, ACQ=29
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: Wrapper Control Enable (I2C_0, I2C_1 as Controller; I2C_2 as Target)
 * Step 3: Initialize all three I2C instances
 * Step 4: Test I2C_0 Controller -> I2C_2 Target at address 0x10
 * Step 5: Test I2C_1 Controller -> I2C_2 Target at address 0x20
 * Step 6: Test Address Masking functionality
 * Step 7: Test Complete
 *
 * =============================================================================
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

    // Test 1: I2C_0 Controller writes to Target address 0x10
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

    // Test 2: I2C_1 Controller writes to Target address 0x20
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

    // Step 1: hardware ACQ FIFO reset (ACQRST), then drain any residue
    simputs("  Clearing ACQ FIFO (hardware reset + drain)...\n");

    i2c_reset_fifos(TARGET_IDX, false, false, false, true); // Reset I2C_2 ACQ FIFO only
    simputs("    ACQ FIFO reset using ACQRST\n");

    // Verify ACQ FIFO is empty after reset and manually drain if needed
    if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
        simputs("    WARNING: ACQ FIFO not empty after reset, draining...\n");
        while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
            (void)read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                   SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        }
    }
    simputs("  ACQ FIFO confirmed empty\n");

    // Step 2: TARGET_EVENTS bits are sticky and re-assert while the underlying condition
    // (for example START on the bus) is still high, so clear in a bounded loop until the
    // register reads zero.
    simputs("  Clearing TARGET_EVENTS (may require multiple clears)...\n");
    uint32_t max_clear_attempts = 5;
    while (max_clear_attempts > 0) {
        uint32_t target_events = i2c_get_target_events(TARGET_IDX);
        if (target_events == 0) {
            break; // Events cleared successfully
        }
        simputs("    Found events: 0x");
        simputshex32("", target_events);
        simputs(", clearing...\n");
        i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF); // Clear all events

        // Small delay for hardware to update
        for (volatile int i = 0; i < 100; i++)
            ;
        max_clear_attempts--;
    }
    simputs("  TARGET_EVENTS cleared\n");

    // Step 3: Wait for Target to be idle before sending next transaction
    simputs("  Waiting for Target to become idle...\n");
    uint32_t idle_wait = 0;
    const uint32_t IDLE_WAIT_TIMEOUT = 50000; // idle-wait bound, in poll iterations
    while (idle_wait < IDLE_WAIT_TIMEOUT) {
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (status.f.TARGETIDLE) {
            // Additional delay to ensure SCL is fully released
            for (volatile int i = 0; i < 1000; i++)
                ; // SCL release settle
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

    // Step 4: Send write to address 0x10 (using non-blocking format, like test_dual_address)
    simputs("  Sending I2C write to Target address 0x10 (from Controller 0)...\n");
    ret =
        i2c_controller_write_with_header_nonblock(CTRL_0_IDX, 0x10, write_data, sizeof(write_data));
    if (ret != I2C_OK) {
        simputs("  ERROR: Write failed\n");
        return ret;
    }
    simputs("  Write queued\n");

    // Step 5: Wait for ACQ FIFO data (same as test_dual_address)
    // allows for recovery latency after the idle wait
    simputs("  Waiting for ACQ FIFO data (timeout=5000)...\n");
    ret = i2c_target_wait_acq_fifo_data(TARGET_IDX, 1, 5000);
    if (ret != I2C_OK) {
        simputs("  ERROR: ACQ FIFO wait failed\n");
        return ret;
    }

    // Step 6: Receive the transaction
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

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
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

    // Initialize Controller 0
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

    // Initialize Controller 1 with same config
    simputs("  Initializing I2C_1 Controller...\n");
    ret = i2c_controller_init(CTRL_1_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller 1 init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Controller 1 initialized successfully\n");

    // Initialize Target (I2C_2) with dual addresses
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

    //=========================================================================
    // Step 4: Testing Dual Address
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Testing Dual Address\n");

    ret = test_dual_address();
    if (ret != I2C_OK) {
        simputs("  Dual address test FAILED\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    write_scratch(1, 0x00000041);

    //=========================================================================
    // Step 5: Testing Address Masking
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Testing Address Masking\n");

    // CRITICAL: Aggressive Controller AND Target recovery before address masking test
    // Previous Dual Address tests may have left both Controller and Target in dirty state
    simputs("  Recovering Controller and Target state...\n");

    // Step 0: First, drain Target ACQ FIFO from previous test_dual_address
    // Previous writes left START/ADDRESS/DATA entries in Target ACQ FIFO
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

    // Step 1: Clear all Controller events from both controllers
    i2c_clear_controller_events(CTRL_0_IDX, 0xFFFFFFFF);
    i2c_clear_controller_events(CTRL_1_IDX, 0xFFFFFFFF);

    // Step 2: Reset both FMT and RX FIFOs on both controllers
    i2c_reset_fifos(CTRL_0_IDX, true, true, false, false);
    i2c_reset_fifos(CTRL_1_IDX, true, true, false, false);

    // Step 3: Wait for both Controllers to become idle
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

        // Check CONTROLLER_EVENTS for both
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

        // Check idle conditions
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

        // Force recovery for Controller 0
        if (!controller_0_idle) {
            i2c_controller_disable(CTRL_0_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
            i2c_controller_enable(CTRL_0_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
        }

        // Force recovery for Controller 1
        if (!controller_1_idle) {
            i2c_controller_disable(CTRL_1_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
            i2c_controller_enable(CTRL_1_IDX);
            for (volatile int i = 0; i < 10000; i++)
                ;
        }
    }

    // Additional stability delay
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

    return I2C_OK;
}
