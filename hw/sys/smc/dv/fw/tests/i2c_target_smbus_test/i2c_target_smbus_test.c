/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C Target SMBus Alert Test - External Master VIP Test
 *
 * =============================================================================
 * Test Purpose
 * =============================================================================
 *
 * This test verifies I2C Target (Slave) mode SMBus Alert functionality:
 *   - Configure I2C_0 as Target mode with address 0x10
 *   - Configure secondary address 0x0C (ARA - Alert Response Address)
 *   - Assert SMBus Alert signal (SMBALERT#)
 *   - Verify VIP detects alert and performs ARA read
 *   - Verify alert is automatically cleared after ARA ACK
 *
 * =============================================================================
 * Test Architecture
 * =============================================================================
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Enable GPIO pad multiplexing
 *   - Configure I2C_0 as Target mode
 *
 * LEVEL 2: OpenTitan I2C IP Control (0xC0009000)
 *   - Configure Target address and timing
 *   - Configure secondary address for ARA (0x0C)
 *   - Enable Target mode reception
 *   - Configure SMBUS_CTRL to assert SMBALERT#
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * 1. System Initialization
 *    - Peripheral reset and clock setup
 *
 * 2. LEVEL 1 - Enable I2C Wrapper (Target mode)
 *    - Enable I2C_0 wrapper control
 *
 * 3. LEVEL 2 - Initialize I2C IP as Target
 *    - Set Target address to 0x10 (primary)
 *    - Set Target address to 0x0C (secondary, ARA)
 *    - Configure timing and FIFO thresholds
 *    - Enable Target mode
 *
 * 4. Assert SMBus Alert
 *    - Configure SMBUS_CTRL.SMBALERT = 1
 *    - Verify SMBALERT# signal is driven low
 *
 * 5. Wait for VIP ARA Read
 *    - VIP detects alert and reads from ARA address (0x0C)
 *    - Target responds with its address (0x20 = 0x10 << 1)
 *    - Alert is automatically cleared after ARA ACK
 *
 * 6. Verify Alert Cleared
 *    - Check SMBUS_STATUS.SMBALERT = 0
 *    - Verify SMBALERT# signal is released (high)
 *
 * =============================================================================
 * SMBus Alert Protocol
 * =============================================================================
 *
 * 1. Target asserts SMBALERT# by setting SMBUS_CTRL.SMBALERT = 1
 * 2. Controller (VIP) detects alert via interrupt or polling
 * 3. Controller reads from Alert Response Address (0x0C)
 * 4. Target with active alert responds with its address (7-bit << 1)
 * 5. Target automatically clears SMBALERT# after ACK
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
 *
 * This is LEVEL 1 of the two-level I2C architecture.
 * Must be done BEFORE configuring the I2C IP.
 *
 * @param idx I2C instance (0 or 1)
 * @param controller_mode true for Controller mode, false for Target mode
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1; // Enable GPIO pad mux
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    ctrl.f.SMBUS_EN = 1; // Required for SMBALERT#/SMBSUS# pad routing

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

/**
 * @brief Check device-side SMBus Alert request (SMBUS_CTRL.SMBALERT)
 *
 * Target asserts alert via CTRL; STATUS.SMBALERT is the host/input observe
 * path and must not be used as the device assert/clear oracle.
 */
static bool smbus_get_alert_ctrl(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__SMBUS_CTRL_t smbus_ctrl = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return smbus_ctrl.f.SMBALERT ? true : false;
}

/**
 * @brief Check SMBus Suspend status (Target mode)
 *
 * @param idx I2C instance index
 * @return true if SMBSUS# is active (low), false otherwise
 */
static bool smbus_get_suspend_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__SMBUS_STATUS_t smbus_status = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return smbus_status.f.SMBSUS ? true : false;
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t TARGET_IDX = 0;    // I2C_0 as Target
    const uint8_t TARGET_ADDR = 0x10; // Target address (7-bit)
    const uint8_t ARA_ADDR = 0x0C;    // Alert Response Address (7-bit)
    int ret;

    //-------------//
    // RESET & PLL //
    //-------------//

    // Hardware releases the peripherals from reset.

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C Target SMBus Alert Test         ##\n");
    simputs("##      (External Master VIP Test)          ##\n");
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
    //         Enable GPIO pad mux (MUST be done FIRST)
    //=========================================================================
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

    // Enable I2C_0 Wrapper (Target mode)
    i2c_wrapper_enable(TARGET_IDX, false);
    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization (Target Mode)
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C Target Initialization\n");

    // Validate I2C target address (7-bit address must be in range 0x08-0x77)
    if (TARGET_ADDR < 0x08 || TARGET_ADDR > 0x77) {
        simputs("  ERROR: Invalid I2C target address\n");
        simputshex32("  Address 0x", TARGET_ADDR);
        simputs(" is outside valid range (0x08-0x77)\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    // Validate ARA address
    if (ARA_ADDR < 0x08 || ARA_ADDR > 0x77) {
        simputs("  ERROR: Invalid ARA address\n");
        simputshex32("  ARA Address 0x", ARA_ADDR);
        simputs(" is outside valid range (0x08-0x77)\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    // Initialize I2C_0 as Target (address 0x10, secondary address 0x0C for ARA)
    simputshex32("  Initializing I2C_0 Target (addr=0x", TARGET_ADDR);
    simputs(", ARA=0x");
    simputshex32("", ARA_ADDR);
    simputs(")...\n");

    // Compute optimal timing parameters from physical characteristics
    i2c_timing_physical_t physical_params = {
        .speed = I2C_SPEED_STANDARD, // 100 kHz
        .clock_period_nanos = 10,    // 100 MHz system clock (1/100MHz = 10ns)
        .sda_rise_nanos = 300,       // Typical for 4.7k pullup
        .sda_fall_nanos = 100,       // Typical fall time
        .scl_period_nanos = 0        // Auto (use minimum for standard mode = 10us)
    };

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    } else {
        simputs("  Using computed timing parameters:\n");
        simputshex32("    THIGH: ", computed_timing.thigh);
        simputshex32("    TLOW:  ", computed_timing.tlow);
        simputshex32("    T_R:   ", computed_timing.t_r);
        simputshex32("    T_F:   ", computed_timing.t_f);
        simputs("\n");
    }

    // Configure Target with primary address (0x10) and secondary address (0x0C for ARA)
    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F,        // Exact match
        .address1 = ARA_ADDR, // Secondary address for ARA
        .mask1 = 0x7F,        // Exact match for ARA
        .timing = computed_timing,
        .fifo = {.tx_thresh = 1, // Set to 1 to ensure target FSM reads TX FIFO immediately
                 .acq_thresh = I2C_DEFAULT_ACQ_THRESH,
                 .rx_thresh = 0,
                 .fmt_thresh = 0},
        .enable_interrupts = false,
        .ack_ctrl_mode = false,
        .tx_stretch_ctrl = false,
        .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");
    simputs("    Primary address: 0x");
    simputshex32("", TARGET_ADDR);

    // Explicitly set ACQ_START_STOP_EN bit to 1
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
    simputs("\n");
    simputs("    Secondary address (ARA): 0x");
    simputshex32("", ARA_ADDR);
    simputs("\n");
    write_scratch(1, 0x00000031);

    // Reset FIFOs after enabling target mode (OpenTitan best practice)
    i2c_reset_fifos(TARGET_IDX, false, false, true, true);
    simputs("  FIFOs reset after target enable\n");

    //=========================================================================
    // Step 4: Assert SMBus Alert
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Asserting SMBus Alert\n");

    // Pre-load TX FIFO with target address for ARA response
    // When VIP reads from ARA address (0x0C), target responds with its address
    // Format: 7-bit address << 1 (I2C format)
    // Example: 0x10 << 1 = 0x20
    uint8_t ara_response = (TARGET_ADDR << 1);
    uint32_t bytes_sent = i2c_target_transmit(TARGET_IDX, &ara_response, 1);
    if (bytes_sent != 1) {
        simputs("  ERROR: Failed to pre-load TX FIFO with ARA response\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    simputs("  Pre-loaded TX FIFO with ARA response: 0x");
    simputshex32("", ara_response);
    simputs(" (address 0x");
    simputshex32("", TARGET_ADDR);
    simputs(" << 1)\n");

    // Assert SMBus Alert by setting SMBUS_CTRL.SMBALERT = 1
    simputs("  Asserting SMBALERT# signal...\n");
    i2c_smbus_alert(TARGET_IDX, true);

    // Add delay to allow signal to propagate to GPIO pad
    // GPIO39 should be driven low by hardware after SMBUS_CTRL.SMBALERT is set
    for (volatile uint32_t i = 0; i < 1000; i++)
        ;

    // Fail-closed: SMBUS_CTRL.SMBALERT must read back asserted before the ARA clear wait
    bool alert_status = smbus_get_alert_ctrl(TARGET_IDX);
    if (!alert_status) {
        simputs("  ERROR: SMBUS_CTRL.SMBALERT not set after i2c_smbus_alert(true)\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    simputs("  SMBALERT# asserted successfully (CTRL.SMBALERT=1)\n");
    bool alert_was_asserted = true;

    // Signal to testbench that alert assertion is complete
    // Testbench will verify GPIO39 signal directly
    write_scratch(1, 0x00000041);
    simputs("  Signal sent to testbench: scratch[1] = 0x00000041\n");

    // Signal setup complete to testbench
    write_scratch(1, 0xEBEDEBE2);
    simputs("  Setup complete - SMBALERT# asserted, waiting for VIP ARA read...\n");

    //=========================================================================
    // Step 5: Wait for VIP ARA Read
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Waiting for VIP ARA Read\n");

    // Wait for VIP to perform ARA read
    // After ARA read with ACK, target automatically clears SMBALERT#
    uint32_t wait_count = 0;
    const uint32_t ARA_WAIT_TIMEOUT = I2C_TIMEOUT_DEFAULT;
    bool alert_cleared = false;

    if (!alert_was_asserted) {
        simputs("  ERROR: Cannot wait for ARA clear without prior asserted status\n");
        write_scratch(0, 0xBAD00052);
        test_fail(0);
    }

    while (wait_count < ARA_WAIT_TIMEOUT) {
        alert_status = smbus_get_alert_ctrl(TARGET_IDX);
        if (!alert_status) {
            /* asserted → cleared edge after ARA ACK */
            alert_cleared = true;
            break;
        }

        wait_count++;
        if (wait_count % 10000 == 0) {
            for (volatile uint32_t i = 0; i < 1000; i++)
                ;
        }
    }

    if (!alert_cleared) {
        simputs("  ERROR: Timeout waiting for alert to clear after ARA read\n");
        simputs("  VIP may not have performed ARA read, or ARA ACK was not received\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }

    simputs("  Alert cleared after ARA read (expected behavior)\n");
    write_scratch(1, 0x00000051);

    //=========================================================================
    // Step 6: Verify Alert Cleared
    //=========================================================================
    write_scratch(1, 0x00000060);
    simputs("\nStep 6: Verifying Alert Cleared\n");

    // Verify alert status is cleared
    alert_status = smbus_get_alert_ctrl(TARGET_IDX);
    if (alert_status) {
        simputs("  ERROR: SMBUS_CTRL.SMBALERT still set after ARA read\n");
        write_scratch(0, 0xBAD00060);
        test_fail(0);
    }

    simputs("  SMBALERT# cleared successfully (CTRL.SMBALERT=0)\n");
    simputs("  Alert was automatically cleared after ARA ACK (SMBus protocol)\n");
    write_scratch(1, 0x00000061);

    //=========================================================================
    // Step 7: Wait for VIP to assert SMBSUS# and verify DUT receives it
    //=========================================================================
    write_scratch(1, 0x00000070);
    simputs("\nStep 7: Waiting for VIP to assert SMBSUS#\n");
    simputs("  VIP will assert SMBSUS# after ARA read completion\n");

    // Wait for VIP to assert SMBSUS# (active low)
    uint32_t suspend_wait_count = 0;
    const uint32_t SUSPEND_WAIT_TIMEOUT = I2C_TIMEOUT_DEFAULT;
    bool suspend_detected = false;

    while (suspend_wait_count < SUSPEND_WAIT_TIMEOUT) {
        bool suspend_status = smbus_get_suspend_status(TARGET_IDX);
        if (suspend_status) {
            // SMBSUS# is active (low) - VIP has asserted suspend
            suspend_detected = true;
            break;
        }

        suspend_wait_count++;
        if (suspend_wait_count % 10000 == 0) {
            for (volatile uint32_t i = 0; i < 1000; i++)
                ;
        }
    }

    if (!suspend_detected) {
        simputs("  ERROR: Timeout waiting for SMBSUS# assertion from VIP\n");
        write_scratch(0, 0xBAD00070);
        test_fail(0);
    }

    simputs("  SMBSUS# detected as asserted (status=1, signal is low)\n");
    simputs("  DUT successfully received SMBSUS# signal from VIP\n");
    write_scratch(1, 0x00000071);

    // Wait a bit for VIP to deassert SMBSUS#
    simputs("  Waiting for VIP to deassert SMBSUS#...\n");
    suspend_wait_count = 0;
    bool suspend_cleared = false;

    while (suspend_wait_count < SUSPEND_WAIT_TIMEOUT) {
        bool suspend_status = smbus_get_suspend_status(TARGET_IDX);
        if (!suspend_status) {
            // SMBSUS# is inactive (high) - VIP has deasserted suspend
            suspend_cleared = true;
            break;
        }

        suspend_wait_count++;
        if (suspend_wait_count % 10000 == 0) {
            for (volatile uint32_t i = 0; i < 1000; i++)
                ;
        }
    }

    if (!suspend_cleared) {
        simputs("  ERROR: Timeout waiting for SMBSUS# deassertion from VIP\n");
        write_scratch(0, 0xBAD00072);
        test_fail(0);
    }
    simputs("  SMBSUS# cleared successfully (status=0, signal is high)\n");
    write_scratch(1, 0x00000072);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    write_scratch(1, 0x00000090);

    // Signal test complete to testbench
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           TEST PASSED                     ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputs("  - I2C_0 (Target):     Addr 0x10 @ 0xC0009000\n");
    simputs("  - ARA Address:        0x0C\n");
    simputs("  - External Master:    cocotbext-i2c VIP\n");
    simputs("  - SMBus Alert:        Asserted and cleared\n");
    simputs("  - ARA Response:       0x20 (0x10 << 1)\n");
    simputs("  - SMBus Suspend:      Detected and cleared\n");
    simputs("  - Verification:       PASS\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
