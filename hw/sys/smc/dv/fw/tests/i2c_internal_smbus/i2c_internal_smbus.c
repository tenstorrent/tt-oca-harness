/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C Internal SMBus Alert Test
 *
 * =============================================================================
 * Test Purpose
 * =============================================================================
 *
 * This test verifies SMBus Alert functionality between two internal I2C instances:
 *   - I2C_0 configured as Target mode
 *   - I2C_1 configured as Controller mode
 *   - Test SMBus Alert signal assertion and detection
 *
 * =============================================================================
 * Test Architecture: Two-Level I2C Control
 * =============================================================================
 *
 * The I2C system uses a two-level architecture:
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Controls GPIO pad multiplexing
 *   - Selects I2C mode (Controller/Target)
 *   - MUST be configured FIRST before IP-level configuration
 *   - Register: I2C_CTRL (per instance)
 *     * Bit[0]: I2C_EN - Enable GPIO pad connection
 *     * Bit[4]: I2C_CONTROLLER_MODE_EN - Mode selection
 *
 * LEVEL 2: IP Control (0xC0009000 + 0x200*idx)
 *   - OpenTitan I2C IP protocol layer
 *   - Handles timing, FIFO, interrupts, transactions
 *   - Base addresses:
 *     * I2C_0: 0xC0009000
 *     * I2C_1: 0xC0009200
 *     * I2C_2: 0xC0009400
 *
 * =============================================================================
 * Test Configuration Details
 * =============================================================================
 *
 * I2C_0 Configuration (Target Mode):
 *   - Target Address: 0x10 (7-bit)
 *   - Address Mask: 0x7F (exact match)
 *   - FIFO Thresholds:
 *     * TX FIFO: 5 entries (target->controller data)
 *     * ACQ FIFO: 29 entries (receive transaction queue)
 *   - Timing: Default (Standard mode, 100 kHz)
 *   - Control Register (0xC0009010):
 *     * ENABLETARGET = 1 (enable target mode)
 *   - SMBUS_CTRL Register (0xC000900C):
 *     * SMBALERT = 1 (drive SMBALERT# line low)
 *
 * I2C_1 Configuration (Controller Mode):
 *   - FIFO Thresholds:
 *     * RX FIFO:  29 entries (received data)
 *     * FMT FIFO: 5 entries (format/command queue)
 *   - Timing: Default (Standard mode, 100 kHz)
 *   - Control Register (0xC0009210):
 *     * ENABLEHOST = 1 (enable controller/host mode)
 *   - Interrupt Enable:
 *     * SMBALERT interrupt enabled to detect alert signal
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 *   - Peripheral reset and clock setup
 *
 * Step 2: LEVEL 1 - Wrapper Control Enable
 *   - Enable I2C_0 Wrapper (Target mode)
 *   - Enable I2C_1 Wrapper (Controller mode)
 *
 * Step 3: LEVEL 2 - I2C IP Initialization
 *   - Initialize I2C_0 as Target (address 0x10)
 *   - Initialize I2C_1 as Controller
 *
 * Step 4: SMBus Alert Configuration
 *   - Enable SMBALERT interrupt on I2C_1 (Controller)
 *   - Verify initial state
 *
 * Step 5: SMBus Alert Test
 *   - Assert SMBus Alert from I2C_0 (Target)
 *   - Verify I2C_1 (Controller) detects the alert interrupt
 *   - Execute Alert Response Address (ARA) protocol
 *   - Verify Target automatically clears SMBALERT after ARA ACK
 *   - Verify Controller reads correct alerting device address
 *   - Test repeatability
 *
 * =============================================================================
 * SMBus Alert Details
 * =============================================================================
 *
 * SMBUS_CTRL Register (offset 0x0C):
 *   - Bit 4: SMBALERT (Target Mode only)
 *     * When set to 1, drives the SMBALERT# line low
 *     * When set to 0, releases the SMBALERT# line
 *
 * INTR_STATE Register:
 *   - Bit 15: SMBALERT interrupt (Controller Mode only)
 *     * Set when SMBALERT# line is detected low
 *     * Write 1 to clear
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
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) + (idx * 4);

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
 * @brief Check SMBus Alert interrupt status on Controller
 *
 * @param idx Controller I2C instance index
 * @return true if SMBALERT interrupt is set, false otherwise
 */
static bool check_smbus_alert_interrupt(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t intr_state = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return (intr_state.f.SMBALERT == 1);
}

/**
 * @brief Clear SMBus Alert interrupt on Controller
 *
 * @param idx Controller I2C instance index
 */
static void clear_smbus_alert_interrupt(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t intr_clear = {.w = 0};
    intr_clear.f.SMBALERT = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_clear.w);
}

/**
 * @brief Enable SMBus Alert interrupt on Controller
 *
 * @param idx Controller I2C instance index
 */
static void enable_smbus_alert_interrupt(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_ENABLE_t intr_enable = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr_enable.f.SMBALERT = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_enable.w);
}

/**
 * @brief Check SMBus Alert control status on Target
 *
 * @param idx Target I2C instance index
 * @return true if SMBALERT is asserted (bit set), false otherwise
 */
static bool check_target_smbus_alert_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__SMBUS_CTRL_t smbus_ctrl = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return (smbus_ctrl.f.SMBALERT == 1);
}

/**
 * @brief Debug: Print Controller FIFO and status information
 *
 * @param idx Controller I2C instance index
 * @param label Debug label string
 */
static void debug_controller_status(uint32_t idx, const char *label) {
    (void)label; // Unused parameter
    uint32_t base = i2c_get_base(idx);

    write_scratch(1, 0x00000070); // Enter debug_controller_status

    // Read all registers first to minimize blocking
    write_scratch(1, 0x00000071); // Before reading HOST_FIFO_STATUS
    uint32_t fmt_status_val =
        read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    (void)fmt_status_val;         // Read for side effects
    write_scratch(1, 0x00000072); // After reading HOST_FIFO_STATUS

    write_scratch(1, 0x00000073); // Before reading STATUS
    uint32_t status_val = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                           SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    (void)status_val;             // Read for side effects
    write_scratch(1, 0x00000074); // After reading STATUS

    write_scratch(1, 0x00000075); // Before reading SMBUS_STATUS
    uint32_t smbus_status_val =
        read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    (void)smbus_status_val;       // Read for side effects
    write_scratch(1, 0x00000076); // After reading SMBUS_STATUS

    // Commented out simputs to avoid blocking - use scratchpad markers instead
    // simputs("  [DEBUG Controller] ");
    // simputs(label);
    // simputs(" FMT:");
    // simputshex32("", fmt_status.f.FMTLVL);
    // simputs(" RX:");
    // simputshex32("", fmt_status.f.RXLVL);
    // simputs(" Status:0x");
    // simputshex32("", status_val);
    // simputs(status.f.HOSTIDLE ? " IDLE" : " BUSY");
    // simputs(" SMBus:0x");
    // simputshex32("", smbus_status_val);
    // if (smbus_status.f.SMBALERT) {
    // 	simputs(" ALERT#_LOW");
    // }
    // simputs("\n");

    write_scratch(1, 0x00000077); // Before exit debug_controller_status
}

/**
 * @brief Debug: Print Target FIFO and status information
 *
 * @param idx Target I2C instance index
 * @param label Debug label string
 */
static void debug_target_status(uint32_t idx, const char *label) {
    (void)label; // Unused parameter
    uint32_t base = i2c_get_base(idx);

    write_scratch(1, 0x00000066); // Enter debug_target_status

    // Read all registers first to minimize blocking
    write_scratch(1, 0x00000067); // Before reading TARGET_FIFO_STATUS
    uint32_t tx_status_val =
        read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    (void)tx_status_val;          // Read for side effects
    write_scratch(1, 0x00000068); // After reading TARGET_FIFO_STATUS

    write_scratch(1, 0x00000069); // Before reading STATUS
    uint32_t status_val = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                           SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    (void)status_val;             // Read for side effects
    write_scratch(1, 0x0000006A); // After reading STATUS

    write_scratch(1, 0x0000006B); // Before reading SMBUS_CTRL
    uint32_t smbus_ctrl_val = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                                               SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    (void)smbus_ctrl_val;         // Read for side effects
    write_scratch(1, 0x0000006C); // After reading SMBUS_CTRL

    // Commented out simputs to avoid blocking - use scratchpad markers instead
    // simputs("  [DEBUG Target] ");
    // simputs(label);
    // simputs(" TX:");
    // simputshex32("", tx_status.f.TXLVL);
    // simputs(" ACQ:");
    // simputshex32("", tx_status.f.ACQLVL);
    // simputs(" Status:0x");
    // simputshex32("", status_val);
    // simputs(status.f.TARGETIDLE ? " IDLE" : " BUSY");
    // simputs(" SMBUS_CTRL:0x");
    // simputshex32("", smbus_ctrl_val);
    // if (smbus_ctrl.f.SMBALERT) {
    // 	simputs(" ALERT");
    // }
    // simputs("\n");

    write_scratch(1, 0x0000006D); // Before exit debug_target_status
}

/**
 * @brief Debug: Print ARA transaction details
 *
 * @param controller_idx Controller I2C instance index
 * @param target_idx Target I2C instance index
 * @param ara_addr ARA address (should be 0x0C)
 * @param read_addr Address read from Target
 * @param expected_addr Expected target address (7-bit)
 */
/**
 * @brief Debug: Print ARA transaction details
 *
 * @param ara_addr ARA address (should be 0x0C)
 * @param read_addr Address read from Target
 * @param expected_addr Expected target address (7-bit)
 */
static void debug_ara_transaction(uint8_t ara_addr, uint8_t read_addr, uint8_t expected_addr) {
    simputs("  [DEBUG ARA Transaction]\n");
    simputs("    Controller reading ARA address: 0x");
    simputshex32("", ara_addr);
    simputs(" (expected: 0x0C)\n");
    simputs("    Target responded with address: 0x");
    simputshex32("", read_addr);
    simputs(" (7-bit: 0x");
    simputshex32("", read_addr >> 1);
    simputs(")\n");

    // Check if address matches expected
    if ((read_addr >> 1) == expected_addr) {
        simputs("    Address match: SUCCESS\n");
    } else {
        simputs("    Address match: FAIL (expected 0x");
        simputshex32("", expected_addr);
        simputs(")\n");
    }
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t TARGET_IDX = 0;     // I2C_0 as Target
    const uint32_t CONTROLLER_IDX = 1; // I2C_1 as Controller
    const uint8_t TARGET_ADDR = 0x10;  // Target address (7-bit)
    int ret;

    //-------------//
    // RESET & PLL //
    //-------------//

    // Note: peripherals_out_of_reset() is no longer available (commented out in smc_io.h)
    // Peripherals are now managed by hardware reset controller

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C Internal SMBus Alert Test         ##\n");
    simputs("################################################\n");
    simputs("\n");

    //=========================================================================
    // Step 1: System Initialization
    //=========================================================================
    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");

    // Note: peripherals_out_of_reset() and program_clocks_quasar()
    // are not needed in this environment (handled by testbench)
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

    // Enable I2C_1 Wrapper (Controller mode)
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    // 3a. Initialize I2C_0 as Target (address 0x10)
    simputs("  Initializing I2C_0 Target (addr=0x10)...\n");

    // Compute optimal timing parameters from physical characteristics
    // Using OpenTitan-inspired physical timing calculation
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

    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F,              // Exact match
        .address1 = SMBUS_ADDR_ARA, // Alert Response Address (0x0C) for SMBus Alert response
        .mask1 = 0x7F,              // Exact match for ARA
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

    // 3b. Initialize I2C_1 as Controller
    simputs("  Initializing I2C_1 Controller...\n");

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
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }
    simputs("  Controller initialized successfully\n");

    write_scratch(1, 0x00000031);

    //=========================================================================
    // Step 4: SMBus Alert Configuration
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: SMBus Alert Configuration\n");

    // Enable SMBALERT interrupt on Controller (I2C_1)
    simputs("  Enabling SMBALERT interrupt on I2C_1 (Controller)...\n");
    enable_smbus_alert_interrupt(CONTROLLER_IDX);
    simputs("  SMBALERT interrupt enabled\n");

    // Verify initial state: no alert interrupt should be set
    simputs("  Checking initial SMBALERT interrupt state...\n");
    if (check_smbus_alert_interrupt(CONTROLLER_IDX)) {
        simputs("  WARNING: SMBALERT interrupt already set before assertion\n");
        clear_smbus_alert_interrupt(CONTROLLER_IDX);
    } else {
        simputs("  Initial state OK: No SMBALERT interrupt (expected)\n");
    }

    write_scratch(1, 0x00000041);

    //=========================================================================
    // Step 5: SMBus Alert Test
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: SMBus Alert Test\n");

    // 5a. Assert SMBus Alert from Target (I2C_0)
    simputs("  Asserting SMBus Alert from I2C_0 (Target)...\n");
    i2c_smbus_alert(TARGET_IDX, true); // Assert alert (drive SMBALERT# low)
    simputs("  SMBus Alert asserted\n");

    // Wait for the signal to propagate and Controller to detect it
    simputs("  Waiting for alert signal propagation to Controller...\n");
    uint32_t wait_count = 0;
    const uint32_t MAX_WAIT = 10000;
    bool alert_detected = false;

    while (wait_count < MAX_WAIT) {
        if (check_smbus_alert_interrupt(CONTROLLER_IDX)) {
            alert_detected = true;
            break;
        }
        wait_count++;
        // Small delay loop to allow signal propagation
        for (volatile uint32_t i = 0; i < 100; i++)
            ;
    }

    if (alert_detected) {
        simputs("  SUCCESS: SMBALERT interrupt detected on I2C_1 (Controller)\n");
        simputshex32("  Wait cycles: ", wait_count);
        simputs("\n");
    } else {
        simputs("  ERROR: SMBALERT interrupt not detected after ");
        simputshex32("", MAX_WAIT);
        simputs(" wait cycles\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }

    write_scratch(1, 0x00000051);

    // 5b. Execute Alert Response Address (ARA) protocol
    simputs("\n  Executing Alert Response Address (ARA) protocol...\n");
    simputs("  Controller reading from ARA address (0x0C)...\n");
    write_scratch(1, 0x00000052); // ARA protocol start marker

    // Debug: Initial state (simplified to avoid blocking)
    write_scratch(1, 0x00000062); // Before starting debug status checks
    simputs("  [PROGRESS] Starting debug status checks...\n");

    write_scratch(1, 0x00000063); // Before Controller debug
    debug_controller_status(CONTROLLER_IDX, "Before ARA");
    write_scratch(1, 0x00000064); // After Controller debug
    simputs("  [PROGRESS] Controller debug done\n");

    write_scratch(1, 0x00000065); // Before Target debug
    debug_target_status(TARGET_IDX, "Before ARA");
    write_scratch(1, 0x00000053); // Target debug done marker
    simputs("  [PROGRESS] Target debug done\n");

    // Verify Target still has SMBALERT asserted before ARA
    write_scratch(1, 0x00000054); // Start checking SMBALERT status
    simputs("  [PROGRESS] Checking Target SMBALERT status...\n");
    if (!check_target_smbus_alert_status(TARGET_IDX)) {
        simputs("  ERROR: Target SMBALERT not asserted before ARA\n");
        write_scratch(0, 0xBAD00051);
        test_fail(0);
    }
    simputs("  Target SMBALERT status: Asserted (expected)\n");
    simputs("  [PROGRESS] Target SMBALERT check done\n");
    write_scratch(1, 0x00000055); // SMBALERT check done marker

    // Prepare Target TX FIFO with its address for ARA response
    // According to SMBus spec, Target must respond to ARA (0x0C) read
    // by sending its own 7-bit address (shifted left by 1 bit)
    // Note: Target address1 is configured as 0x0C (ARA) to respond to ARA reads
    write_scratch(1, 0x00000056); // Start preparing TX FIFO
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Preparing Target TX FIFO...\n");
    // simputs("  Preparing Target TX FIFO with address for ARA response...\n");
    // simputs("  Target configured with address0=0x");
    // simputshex32("", TARGET_ADDR);
    // simputs(", address1=0x");
    // simputshex32("", SMBUS_ADDR_ARA);
    // simputs(" (ARA)\n");

    uint8_t target_addr_byte = (TARGET_ADDR << 1); // 7-bit address << 1 for I2C format
    write_scratch(1, 0x00000057);                  // Before calling i2c_target_transmit
    // Commented out simputs to avoid blocking窄謢窄謢
    // simputs("  [PROGRESS] Calling i2c_target_transmit...\n");
    uint32_t written = i2c_target_transmit(TARGET_IDX, &target_addr_byte, 1);
    write_scratch(1, 0x00000058); // After i2c_target_transmit
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] i2c_target_transmit returned: ");
    // simputshex32("", written);
    // simputs("\n");

    if (written != 1) {
        // Commented out simputs to avoid blocking
        // simputs("  ERROR: Failed to prepare Target TX FIFO for ARA response\n");
        write_scratch(0, 0xBAD00051);
        test_fail(0);
    }
    // Commented out simputs to avoid blocking
    // simputs("  Target TX FIFO prepared with address: 0x");
    // simputshex32("", target_addr_byte);
    // simputs("\n");

    // Debug: After preparing TX FIFO (simplified)
    write_scratch(1, 0x00000059); // Before debug after TX FIFO
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Debug after TX FIFO prep...\n");
    debug_target_status(TARGET_IDX, "After TX FIFO");
    debug_controller_status(CONTROLLER_IDX, "Before ARA cmd");
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Debug done\n");
    write_scratch(1, 0x0000005A); // Debug done marker

    // Execute ARA read: Controller reads from Alert Response Address (0x0C)
    write_scratch(1, 0x0000005B); // Start ARA read transaction
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Starting ARA read transaction...\n");
    // simputs("  Executing ARA read transaction...\n");
    // simputs("  Controller sending START + ARA address (0x0C << 1 | 1 = 0x19)...\n");

    // Check Controller idle before ARA read
    write_scratch(1, 0x0000005C); // Before waiting for Controller idle
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Waiting for Controller to be idle...\n");
    int idle_ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_TIMEOUT_DEFAULT);
    write_scratch(1, 0x0000005D); // After waiting for Controller idle
    if (idle_ret != I2C_OK) {
        // Commented out simputs to avoid blocking
        // simputs("  ERROR: Controller not idle before ARA read (error: ");
        // simputshex32("", idle_ret);
        // simputs(")\n");
        write_scratch(0, 0xBAD00052);
        test_fail(0);
    }
    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Controller is idle, proceeding with ARA read...\n");
    write_scratch(1, 0x0000005E); // Controller idle confirmed

    uint8_t alert_addr = 0;
    write_scratch(1, 0x0000005F); // Before calling smbus_alert_response

    // Check Controller and Target status before ARA read
    uint32_t ctrl_events_before = i2c_get_controller_events(CONTROLLER_IDX);
    uint32_t tgt_tx_level_before, tgt_acq_level_before;
    i2c_target_get_fifo_status(TARGET_IDX, &tgt_tx_level_before, &tgt_acq_level_before);
    uint32_t tgt_base_before = i2c_get_base(TARGET_IDX);
    i2c__STATUS_t tgt_status_before = {
        .w = read_reg(tgt_base_before + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    // Commented out simputs to avoid blocking
    // simputs("  [PROGRESS] Calling smbus_alert_response...\n");
    ret = smbus_alert_response(CONTROLLER_IDX, &alert_addr);
    write_scratch(1, 0x00000060); // After smbus_alert_response returned

    // Check Controller and Target status after ARA read attempt
    uint32_t ctrl_events_after = i2c_get_controller_events(CONTROLLER_IDX);
    uint32_t tgt_tx_level_after, tgt_acq_level_after;
    i2c_target_get_fifo_status(TARGET_IDX, &tgt_tx_level_after, &tgt_acq_level_after);
    uint32_t tgt_base_after = i2c_get_base(TARGET_IDX);
    i2c__STATUS_t tgt_status_after = {
        .w = read_reg(tgt_base_after + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                        SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    simputs("  [PROGRESS] smbus_alert_response returned: ");
    simputshex32("", ret);
    simputs("\n");
    simputs("  [DEBUG] Before ARA: CtrlEvents=0x");
    simputshex32("", ctrl_events_before);
    simputs(", TgtTX=");
    simputshex32("", tgt_tx_level_before);
    simputs(", TgtACQ=");
    simputshex32("", tgt_acq_level_before);
    simputs(", TgtIdle=");
    simputshex32("", tgt_status_before.f.TARGETIDLE);
    simputs("\n");
    simputs("  [DEBUG] After ARA:  CtrlEvents=0x");
    simputshex32("", ctrl_events_after);
    simputs(", TgtTX=");
    simputshex32("", tgt_tx_level_after);
    simputs(", TgtACQ=");
    simputshex32("", tgt_acq_level_after);
    simputs(", TgtIdle=");
    simputshex32("", tgt_status_after.f.TARGETIDLE);
    simputs("\n");

    if (ret != I2C_OK) {
        simputs("  ERROR: ARA read failed with error code: ");
        simputshex32("", ret);
        simputs("\n");

        // Check Controller Events for error details
        uint32_t events = i2c_get_controller_events(CONTROLLER_IDX);
        simputs("  Controller Events: ");
        simputshex32("0x", events);
        simputs(" (");
        if (events & 0x1) simputs("NACK ");
        if (events & 0x8) simputs("ARB_LOST ");
        if (events & 0x4) simputs("BUS_TIMEOUT ");
        if (events & 0x2) simputs("NACK_TIMEOUT ");
        simputs(")\n");

        // Check Target ACQ FIFO to see if it received the address
        simputs("  [PROGRESS] Checking Target ACQ FIFO...\n");
        uint32_t tx_level, acq_level;
        i2c_target_get_fifo_status(TARGET_IDX, &tx_level, &acq_level);
        simputs("  Target ACQ FIFO:");
        simputshex32("", acq_level);
        simputs("\n");

        simputs("  [PROGRESS] Checking Controller status...\n");
        debug_controller_status(CONTROLLER_IDX, "After FAILED");
        write_scratch(0, 0xBAD00052);
        test_fail(0);
    }

    simputs("  ARA read successful\n");
    simputshex32("  Alerting device address: 0x", alert_addr);
    simputs("\n");

    // Debug: ARA transaction details
    debug_ara_transaction(SMBUS_ADDR_ARA, alert_addr, TARGET_ADDR);

    // Debug: After ARA read (simplified)
    simputs("  [PROGRESS] Debug after ARA read...\n");
    debug_controller_status(CONTROLLER_IDX, "After ARA");
    debug_target_status(TARGET_IDX, "After ARA");
    simputs("  [PROGRESS] Debug done\n");

    // Verify correct address was read
    if (alert_addr != TARGET_ADDR) {
        simputs("  ERROR: Incorrect alert address read\n");
        simputshex32("  Expected: 0x", TARGET_ADDR);
        simputshex32(", Got: 0x", alert_addr);
        simputs("\n");
        write_scratch(0, 0xBAD00053);
        test_fail(0);
    }
    simputs("  SUCCESS: Correct alert address read\n");

    // Wait for Target to automatically clear SMBALERT after ARA ACK
    simputs("  Waiting for Target to auto-clear SMBALERT after ARA ACK...\n");
    wait_count = 0;
    const uint32_t MAX_CLEAR_WAIT = 5000;
    bool alert_cleared = false;

    while (wait_count < MAX_CLEAR_WAIT) {
        if (!check_target_smbus_alert_status(TARGET_IDX)) {
            alert_cleared = true;
            break;
        }
        wait_count++;
        for (volatile uint32_t i = 0; i < 100; i++)
            ;
    }

    if (alert_cleared) {
        simputs("  SUCCESS: Target automatically cleared SMBALERT after ARA\n");
        simputshex32("  Clear wait cycles: ", wait_count);
        simputs("\n");
    } else {
        simputs("  ERROR: Target did not auto-clear SMBALERT after ARA\n");
        write_scratch(0, 0xBAD00054);
        test_fail(0);
    }

    // Clear the interrupt on Controller
    simputs("  Clearing SMBALERT interrupt on I2C_1 (Controller)...\n");
    clear_smbus_alert_interrupt(CONTROLLER_IDX);

    // Wait a bit and verify interrupt is cleared
    wait_count = 0;
    while (wait_count < 1000) {
        if (!check_smbus_alert_interrupt(CONTROLLER_IDX)) {
            break;
        }
        wait_count++;
        for (volatile uint32_t i = 0; i < 100; i++)
            ;
    }

    if (!check_smbus_alert_interrupt(CONTROLLER_IDX)) {
        simputs("  SUCCESS: SMBALERT interrupt cleared successfully\n");
    } else {
        simputs("  ERROR: SMBALERT interrupt still set after clearing\n");
        write_scratch(0, 0xBAD00055);
        test_fail(0);
    }

    write_scratch(1, 0x00000052);

    // 5c. Test alert assertion again to verify repeatability
    simputs("\n  Testing alert assertion again (repeatability test)...\n");
    i2c_smbus_alert(TARGET_IDX, true);

    wait_count = 0;
    alert_detected = false;
    while (wait_count < MAX_WAIT) {
        if (check_smbus_alert_interrupt(CONTROLLER_IDX)) {
            alert_detected = true;
            break;
        }
        wait_count++;
        for (volatile uint32_t i = 0; i < 100; i++)
            ;
    }

    if (alert_detected) {
        simputs("  SUCCESS: Second alert assertion detected successfully\n");
    } else {
        simputs("  ERROR: Second alert assertion not detected\n");
        write_scratch(0, 0xBAD00056);
        test_fail(0);
    }

    // Prepare Target TX FIFO again for second ARA response
    simputs("  Preparing Target TX FIFO for second ARA response...\n");
    target_addr_byte = (TARGET_ADDR << 1);
    written = i2c_target_transmit(TARGET_IDX, &target_addr_byte, 1);
    if (written != 1) {
        simputs("  ERROR: Failed to prepare Target TX FIFO for second ARA response\n");
        write_scratch(0, 0xBAD00056);
        test_fail(0);
    }

    // Debug: Before second ARA
    debug_target_status(TARGET_IDX, "Before second ARA - TX FIFO prepared");
    debug_controller_status(CONTROLLER_IDX, "Before second ARA read");

    // Execute ARA again for repeatability
    simputs("  Executing ARA protocol again...\n");
    alert_addr = 0;
    ret = smbus_alert_response(CONTROLLER_IDX, &alert_addr);

    if (ret != I2C_OK) {
        simputs("  ERROR: Second ARA read failed\n");
        debug_controller_status(CONTROLLER_IDX, "After second ARA read FAILED");
        debug_target_status(TARGET_IDX, "After second ARA read FAILED");
        write_scratch(0, 0xBAD00057);
        test_fail(0);
    }

    // Debug: Second ARA transaction
    debug_ara_transaction(SMBUS_ADDR_ARA, alert_addr, TARGET_ADDR);
    debug_controller_status(CONTROLLER_IDX, "After second ARA read");
    debug_target_status(TARGET_IDX, "After second ARA read");

    if (alert_addr != TARGET_ADDR) {
        simputs("  ERROR: Incorrect alert address in second ARA read\n");
        write_scratch(0, 0xBAD00058);
        test_fail(0);
    }

    // Wait for auto-clear
    wait_count = 0;
    alert_cleared = false;
    while (wait_count < MAX_CLEAR_WAIT) {
        if (!check_target_smbus_alert_status(TARGET_IDX)) {
            alert_cleared = true;
            break;
        }
        wait_count++;
        for (volatile uint32_t i = 0; i < 100; i++)
            ;
    }

    if (alert_cleared) {
        simputs("  SUCCESS: Second ARA completed, Target auto-cleared SMBALERT\n");
    } else {
        simputs("  ERROR: Target did not auto-clear SMBALERT after second ARA\n");
        write_scratch(0, 0xBAD00059);
        test_fail(0);
    }

    // Clean up: clear interrupt
    clear_smbus_alert_interrupt(CONTROLLER_IDX);

    write_scratch(1, 0x00000061); // ARA Protocol Complete (repeatability test done)

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
    simputs("  - I2C_0 (Target):     Addr 0x10 @ 0xC0009000\n");
    simputs("  - I2C_1 (Controller): @ 0xC0009200\n");
    simputs("  - SMBus Alert:        PASS\n");
    simputs("    * Alert assertion detected\n");
    simputs("    * ARA protocol executed successfully\n");
    simputs("    * Target auto-cleared SMBALERT after ARA ACK\n");
    simputs("    * Correct alert address read (0x10)\n");
    simputs("    * Repeatability test passed\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
