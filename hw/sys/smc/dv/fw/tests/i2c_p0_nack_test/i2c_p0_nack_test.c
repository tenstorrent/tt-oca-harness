/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C NACK Test
 *
 * Test Description:
 * - Configure I2C_0 as Controller (Master)
 * - Send transactions to VIP slave
 * - Test Case 1: VIP slave sends NACK at address phase
 * - Test Case 2: VIP slave sends NACK at data phase
 * - Monitor master status registers for abort and NACK events
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

// Test configuration
const uint32_t CONTROLLER_IDX = 0;         // I2C_0 as Controller
const uint32_t TARGET_IDX = 1;             // I2C_1 as internal Target (positive control)
const uint8_t VIP_SLAVE_ADDR = 0x10;       // VIP slave address (7-bit)
const uint8_t INTERNAL_TARGET_ADDR = 0x20; // Internal allow-path target

/**
 * @brief Enable I2C Wrapper Control
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1; // Enable GPIO pad mux
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

/**
 * @brief Read I2C Controller Events register
 */
static uint32_t read_controller_events(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    return read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0) -
                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
}

/**
 * @brief Clear I2C Controller Events register
 */
static void clear_controller_events(uint32_t idx, uint32_t event_mask) {
    uint32_t base = i2c_get_base(idx);
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              event_mask);
}

/**
 * @brief Check and report controller status
 */
static void check_controller_status(uint32_t idx, const char *label) {
    uint32_t base = i2c_get_base(idx);
    i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    uint32_t events = read_controller_events(idx);

    simputs("  [STATUS] ");
    simputs(label);
    simputs("\n");
    simputs("    STATUS: hostidle=");
    simputshex32("", status.f.HOSTIDLE);
    simputs(", fmtempty=");
    simputshex32("", status.f.FMTEMPTY);
    simputs(", rxempty=");
    simputshex32("", status.f.RXEMPTY);
    simputs("\n");
    simputs("    EVENTS: nack=");
    simputshex32("", (events >> 0) & 0x1);
    simputs(", unhandled_nack_timeout=");
    simputshex32("", (events >> 1) & 0x1);
    simputs(", bus_timeout=");
    simputshex32("", (events >> 2) & 0x1);
    simputs(", arbitration_lost=");
    simputshex32("", (events >> 3) & 0x1);
    simputs("\n");
}

/**
 * @brief Positive control: ACK'd write to internal I2C_1 target.
 * Proves the controller allow-path before NACK injection legs.
 */
static int test_ack_positive_control(uint32_t controller_idx, uint32_t target_idx,
                                     uint8_t target_addr, const i2c_timing_config_t *timing) {
    simputs("\n=== Positive Control: ACK allow-path (I2C_1 target) ===\n");

    i2c_wrapper_enable(target_idx, false);

    i2c_target_config_t tgt_cfg = {.address0 = target_addr,
                                   .mask0 = 0x7F,
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = *timing,
                                   .fifo = {.tx_thresh = I2C_DEFAULT_TX_THRESH,
                                            .acq_thresh = I2C_DEFAULT_ACQ_THRESH,
                                            .rx_thresh = 0,
                                            .fmt_thresh = 0},
                                   .enable_interrupts = false,
                                   .ack_ctrl_mode = false,
                                   .tx_stretch_ctrl = false,
                                   .timeout_cycles = 0};

    int ret = i2c_target_init(target_idx, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Internal target init failed\n");
        return ret;
    }

    uint32_t tgt_base = i2c_get_base(target_idx);
    i2c__CTRL_t ctrl = {.w = read_reg(tgt_base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(tgt_base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              ctrl.w);

    clear_controller_events(controller_idx, 0xF);
    ret = i2c_controller_wait_idle(controller_idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller not idle before allow-path\n");
        return ret;
    }

    uint8_t payload[1] = {0x5A};
    ret = i2c_controller_write(controller_idx, target_addr, payload, 1, true);
    if (ret != I2C_OK) {
        simputs("  ERROR: Allow-path write failed\n");
        return ret;
    }

    ret = i2c_controller_wait_idle(controller_idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller did not return idle after allow-path\n");
        return ret;
    }

    uint32_t events = read_controller_events(controller_idx);
    if (events & 0x1) {
        simputs("  ERROR: NACK set on allow-path (unexpected)\n");
        return I2C_ERROR;
    }

    simputs("  PASS: Allow-path write completed with idle and no NACK\n");
    clear_controller_events(controller_idx, 0xF);
    return I2C_OK;
}

/**
 * @brief Test Case 1: NACK at address phase
 */
static int test_nack_at_address(uint32_t controller_idx, uint8_t target_addr) {
    simputs("\n=== Test Case 1: NACK at Address Phase ===\n");

    // Clear events before test
    clear_controller_events(controller_idx, 0xF);

    // Wait for controller idle
    int ret = i2c_controller_wait_idle(controller_idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller not idle\n");
        return ret;
    }

    check_controller_status(controller_idx, "Before transaction");

    // Send START + address (write bit = 0)
    // VIP slave will NACK at address phase
    uint32_t base = i2c_get_base(controller_idx);
    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = (target_addr << 1) | 0x0; // Write bit = 0
    fdata.f.START = 1;
    fdata.f.STOP = 1; // Send STOP after transaction
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    simputs("  Sent START + address (expecting NACK)...\n");

    // Wait for transaction to complete (controller becomes idle or error occurs)
    uint32_t timeout = I2C_TIMEOUT_DEFAULT;
    uint32_t count = 0;
    while (count < timeout) {
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        uint32_t events = read_controller_events(controller_idx);

        // Check for NACK event
        if (events & 0x1) {
            simputs("  NACK detected!\n");
            check_controller_status(controller_idx, "After NACK");

            /* RTL ClockPulseAck halt: hostidle must stay 0 until SW recover. */
            if (status.f.HOSTIDLE != 0) {
                simputs("  ERROR: Controller idle after NACK (expected halt)\n");
                return I2C_ERROR;
            }
            simputs("  PASS: Controller halted after NACK\n");

            // Clear events for next test
            clear_controller_events(controller_idx, 0xF);
            return I2C_OK;
        }

        // Check if controller is idle (transaction completed)
        if (status.f.HOSTIDLE == 1) {
            simputs("  WARNING: Controller idle without NACK event\n");
            return I2C_ERROR;
        }

        count++;
    }

    simputs("  ERROR: Timeout waiting for NACK\n");
    check_controller_status(controller_idx, "After timeout");
    return I2C_ERROR_TIMEOUT;
}

/**
 * @brief Test Case 2: NACK at data phase
 */
static int test_nack_at_data(uint32_t controller_idx, uint8_t target_addr) {
    simputs("\n=== Test Case 2: NACK at Data Phase ===\n");

    // Clear events before test
    clear_controller_events(controller_idx, 0xF);

    // Wait for controller idle
    int ret = i2c_controller_wait_idle(controller_idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller not idle\n");
        return ret;
    }

    check_controller_status(controller_idx, "Before transaction");

    // Send START + address + data + STOP in sequence
    // VIP slave will NACK at data phase after acknowledging address
    uint32_t base = i2c_get_base(controller_idx);
    i2c__FDATA_t fdata = {.w = 0};

    // Send START + address (write bit = 0)
    fdata.f.FBYTE = (target_addr << 1) | 0x0; // Write bit = 0
    fdata.f.START = 1;
    fdata.f.STOP = 0; // No STOP yet
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    // Send data byte - VIP should NACK this at data phase
    fdata.w = 0;
    fdata.f.FBYTE = 0xAA; // Test data byte
    fdata.f.START = 0;    // START already sent
    fdata.f.STOP = 1;     // Send STOP after data
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    // Bounded poll for CONTROLLER_EVENTS.nack
    uint32_t timeout = I2C_TIMEOUT_DEFAULT;
    uint32_t count = 0;
    while (count < timeout) {
        uint32_t events = read_controller_events(controller_idx);
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (events & 0x1) {
            simputs("  NACK detected at data phase!\n");
            check_controller_status(controller_idx, "After data NACK");
            /* RTL ClockPulseAck halt: hostidle must stay 0 until SW recover. */
            if (status.f.HOSTIDLE != 0) {
                simputs("  ERROR: Controller idle after data NACK (expected halt)\n");
                return I2C_ERROR;
            }
            simputs("  PASS: Controller halted after data NACK\n");
            clear_controller_events(controller_idx, 0xF);
            return I2C_OK;
        }

        count++;
    }

    simputs("  ERROR: Timeout waiting for data-phase NACK event\n");
    check_controller_status(controller_idx, "After timeout");
    return I2C_ERROR_TIMEOUT;
}

int main(void) {
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##           I2C NACK Test                   ##\n");
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

    // Enable I2C_0 Wrapper (Controller mode)
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");
    simputs("  Initializing I2C_0 Controller...\n");

    // Compute timing parameters
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD, // 100 kHz
                                             .clock_period_nanos = 10,    // 100 MHz system clock
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    // Initialize I2C_0 as Controller
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

    //=========================================================================
    // Positive control: ACK allow-path via the internal I2C_1 target before any
    // VIP NACK injection. Address 0x20 does not collide with VIP_SLAVE_ADDR (0x10).
    //=========================================================================
    write_scratch(1, 0x00000035);
    ret = test_ack_positive_control(CONTROLLER_IDX, TARGET_IDX, INTERNAL_TARGET_ADDR,
                                    &computed_timing);
    if (ret != I2C_OK) {
        simputs("  ERROR: Positive allow-path control failed\n");
        write_scratch(0, 0xBAD00035);
        test_fail(0);
    }
    write_scratch(1, 0x00000036);

    write_scratch(1, 0x00000031);

    simputs("  Firmware init complete, reading test case selection...\n");

    //=========================================================================
    // Read test case selection from scratch register 3
    // Bit 0 = run Test Case 1, Bit 1 = run Test Case 2
    // Default to both if scratch 3 is 0
    // Note: scratch[2] is used by virtual console, so we use scratch[3] instead
    //=========================================================================
    uint32_t test_case_mask = read_scratch(3);
    simputs("  Read scratch[3] successfully\n");
    bool run_test1 = (test_case_mask & 0x1) != 0;
    bool run_test2 = (test_case_mask & 0x2) != 0;

    // If no test cases selected, default to both
    if (test_case_mask == 0) {
        run_test1 = true;
        run_test2 = true;
        simputs("  No test case selection in scratch[3], running both test cases\n");
    } else {
        simputs("  Test case selection from scratch[3]: ");
        simputshex32("mask=0x", test_case_mask);
        simputs(", TC1=");
        simputshex32("", run_test1);
        simputs(", TC2=");
        simputshex32("", run_test2);
        simputs("\n");
    }

    //=========================================================================
    // Step 4: Test Case 1 - NACK at Address Phase
    //=========================================================================
    if (run_test1) {
        write_scratch(1, 0x00000040);
        ret = test_nack_at_address(CONTROLLER_IDX, VIP_SLAVE_ADDR);
        if (ret != I2C_OK) {
            simputs("  ERROR: Test Case 1 failed\n");
            write_scratch(0, 0xBAD00040);
            test_fail(0);
        }
        write_scratch(1, 0x00000041);

        // Recover controller after Test Case 1 (NACK halted the controller)
        simputs("\nRecovering controller after Test Case 1...\n");

        // Step 1: Clear all events
        clear_controller_events(CONTROLLER_IDX, 0xF);

        // Step 2: Reset FMT FIFO and RX FIFO to clear any residual data
        // This is required after NACK halt according to OpenTitan I2C spec
        i2c_reset_fifos(CONTROLLER_IDX, true, true, false, false);

        // Step 3: Wait for controller to become idle
        ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) {
            simputs("  WARNING: Controller recovery timeout, but continuing...\n");
        } else {
            simputs("  Controller recovered successfully\n");
        }

        check_controller_status(CONTROLLER_IDX, "After recovery");

        // Wait a bit between tests
        for (volatile int i = 0; i < 10000; i++)
            ;
    } else {
        simputs("\nSkipping Test Case 1 (not selected)\n");
    }

    //=========================================================================
    // Step 5: Test Case 2 - NACK at Data Phase
    //=========================================================================
    if (run_test2) {
        write_scratch(1, 0x00000050);
        ret = test_nack_at_data(CONTROLLER_IDX, VIP_SLAVE_ADDR);
        if (ret != I2C_OK) {
            simputs("  ERROR: Test Case 2 failed\n");
            write_scratch(0, 0xBAD00050);
            test_fail(0);
        }
        write_scratch(1, 0x00000051);
    } else {
        simputs("\nSkipping Test Case 2 (not selected)\n");
    }

    //=========================================================================
    // Test Complete
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
    simputs("  - VIP Slave Address: 0x");
    simputshex32("", VIP_SLAVE_ADDR);
    simputs("\n");
    if (run_test1) {
        simputs("  - Test Case 1 (NACK at address): PASS\n");
    }
    if (run_test2) {
        simputs("  - Test Case 2 (NACK at data): PASS\n");
    }
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
