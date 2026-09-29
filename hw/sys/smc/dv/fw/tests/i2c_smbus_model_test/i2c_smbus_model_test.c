/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_smbus_model_test.c
 * @brief I2C SMBus Alert Test against the SV SMBus peer - OpenTitan I2C Version
 *
 * =============================================================================
 * Test Purpose
 * =============================================================================
 *
 * This test verifies SMBus Alert and Suspend functionality of the OpenTitan
 * I2C IP:
 *   - SMBus Alert (SMBALERT#): Device -> Host signal propagation
 *   - Alert Response Address (ARA): Host reads alert source
 *   - Interrupt status and clearing (INTR_STATE.SMBALERT set, then W1C)
 *
 * SMBSUS# is driven in Step 5 but is NOT verified here -- see the Step 5 note
 * in the Test Flow section below.
 *
 * =============================================================================
 * Test Architecture
 * =============================================================================
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Controls GPIO pad multiplexing
 *   - Selects I2C mode (Controller/Target)
 *   - MUST be configured FIRST before IP-level configuration
 *
 * LEVEL 2: OpenTitan I2C IP Control (0xC0009000 + 0x200*idx)
 *   - OpenTitan I2C IP protocol layer
 *   - Handles SMBus Alert/Suspend signals
 *   - Base addresses:
 *     * I2C_0: 0xC0009000 (Target/Device)
 *     * I2C_1: 0xC0009200 (Controller/Host)
 *     * I2C_2: 0xC0009400 (Controller/Host)
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * 1. System Initialization
 *    - Peripheral reset and clock setup
 *
 * 2. LEVEL 1 - Enable I2C Wrapper
 *    - Enable I2C_0 as Controller mode (for ARA read)
 *
 * 3. LEVEL 2 - Initialize I2C IP
 *    - Initialize I2C_0 as Controller
 *    - External SV model (pmbus_slave_i2c0 @ 0x40) acts as Target
 *
 * 4. Test SMBus Alert (Device -> Host)
 *    - Device asserts SMBALERT#
 *    - Host detects alert status
 *    - Host detects alert interrupt
 *    - Host performs ARA read (0x0C)
 *    - Verify alert cleared after ARA
 *
 * 5. Drive SMBus Suspend (Host -> Device) -- stimulus only, not checked
 *    - Host asserts SMBSUS#, then deasserts it
 *    - Nothing observes it: the SMBus peer in this testbench
 *      (tb_uvm/sv/I2C_SMBUS_MODEL.sv) hardwires SMBSUS_N = 1'bz and samples
 *      that pin nowhere, so no "device detected suspend" fact exists to check
 *      and none is reported. See Step 5 below.
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
 * @param idx I2C instance (0, 1, or 2)
 * @param controller_mode true for Controller mode, false for Target mode
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1; // Enable GPIO pad mux
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    ctrl.f.SMBUS_EN = 1; // Enable SMBus functionality (CRITICAL for SMBALERT#/SMBSUS# routing)

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputshex32(", ctrl_val=0x", ctrl.w);
    simputs("\n");
}

/**
 * @brief Wait until condition is met or timeout
 *
 * @param cond_fn Function pointer to condition check function
 * @param idx I2C instance index
 * @param expected Expected value
 * @param timeout_cycles Timeout in cycles
 * @return true if condition met, false if timeout
 */
static bool wait_until(bool (*cond_fn)(uint32_t), uint32_t idx, bool expected,
                       uint32_t timeout_cycles) {
    uint32_t elapsed = 0;
    uint32_t check_interval = timeout_cycles / 10; // Check every 10% of timeout
    if (check_interval == 0) check_interval = 1;

    while (timeout_cycles--) {
        if (cond_fn(idx) == expected) {
            if (elapsed > 0) {
                simputs("  [TIMEOUT] Condition met after ");
                simputshex32("", elapsed);
                simputs(" cycles\n");
            }
            return true;
        }
        elapsed++;

        // Periodic progress report
        if ((elapsed % check_interval) == 0 && elapsed > 0) {
            uint32_t progress = (elapsed * 100) / (elapsed + timeout_cycles);
            simputs("  [TIMEOUT] Waiting... elapsed=");
            simputshex32("", elapsed);
            simputs(" cycles (");
            simputshex32("", progress);
            simputs("%), remaining=");
            simputshex32("", timeout_cycles);
            simputs(" cycles\n");
        }
    }

    simputs("  [TIMEOUT] TIMEOUT after ");
    simputshex32("", elapsed);
    simputs(" cycles - condition not met!\n");
    simputs("  [TIMEOUT] Expected condition: ");
    simputs(expected ? "true" : "false");
    simputs("\n");
    simputs("  [TIMEOUT] Actual condition: ");
    simputs(cond_fn(idx) ? "true" : "false");
    simputs("\n");
    return false;
}

//=============================================================================
// SMBus Alert Functions
//=============================================================================

/**
 * @brief Check SMBus Alert status (Controller mode)
 *
 * Samples SMBUS_STATUS.SMBALERT three times with a short delay between reads and
 * reports active when at least two samples agree.
 *
 * @param idx I2C instance index
 * @return true if SMBALERT# is active (low), false otherwise
 */
static bool smbus_get_alert_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    bool status1, status2, status3;

    // Read 1: Initial read
    i2c__SMBUS_STATUS_t smbus_status1 = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    status1 = smbus_status1.f.SMBALERT ? true : false;

    // Settle between samples
    for (volatile int i = 0; i < 100; i++)
        ;

    // Read 2: Confirmation read
    i2c__SMBUS_STATUS_t smbus_status2 = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    status2 = smbus_status2.f.SMBALERT ? true : false;

    // Settle between samples
    for (volatile int i = 0; i < 100; i++)
        ;

    // Read 3: Final confirmation
    i2c__SMBUS_STATUS_t smbus_status3 = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    status3 = smbus_status3.f.SMBALERT ? true : false;

    // Majority of the three samples
    int active_count = (status1 ? 1 : 0) + (status2 ? 1 : 0) + (status3 ? 1 : 0);
    return active_count >= 2;
}

/**
 * @brief Check SMBus Alert interrupt status
 *
 * Reads INTR_STATE.SMBALERT twice and also accepts SMBUS_STATUS.SMBALERT.
 *
 * @param idx I2C instance index
 * @return true if alert interrupt is pending, false otherwise
 */
static bool smbus_irq_alert_stat(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    bool intr1, intr2;

    // Method 1: Check INTR_STATE register
    i2c__INTR_STATE_t intr_state = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr1 = intr_state.f.SMBALERT ? true : false;

    // Settle between reads
    for (volatile int i = 0; i < 50; i++)
        ;

    // Method 2: Re-read for confirmation
    i2c__INTR_STATE_t intr_state2 = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr2 = intr_state2.f.SMBALERT ? true : false;

    // Also check if SMBus status indicates alert (as backup verification)
    bool smbus_alert_active = smbus_get_alert_status(idx);

    // Either INTR_STATE read or the SMBUS_STATUS sample counts as alert
    return intr1 || intr2 || smbus_alert_active;
}

/**
 * @brief INTR_STATE.SMBALERT, and nothing else.
 *
 * Deliberately not smbus_irq_alert_stat(): that one ORs in
 * smbus_get_alert_status(), which is the same SMBUS_STATUS predicate that
 * already gated CHECKERs 1/2, so it reports "interrupt pending" on a DUT whose
 * SMBALERT interrupt never fires. CHECKERs 3/5 name the interrupt, so they have
 * to sample the interrupt.
 *
 * @param idx I2C instance index
 * @return true if INTR_STATE.SMBALERT is set
 */
static bool smbus_intr_alert_only(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t intr_state = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return intr_state.f.SMBALERT ? true : false;
}

/**
 * @brief Clear SMBus Alert interrupt
 *
 * @param idx I2C instance index
 */
static void smbus_clear_alert_irq(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t intr_clear = {.w = 0};
    intr_clear.f.SMBALERT = 1; // Write 1 to clear
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_clear.w);
}

//=============================================================================
// SMBus Suspend Functions
//=============================================================================

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

/**
 * @brief Check SMBus Suspend interrupt status
 *
 * @param idx I2C instance index
 * @return true if suspend interrupt is pending, false otherwise
 */
static bool smbus_irq_suspend_stat(uint32_t idx) {
    (void)idx; // Suppress unused parameter warning
    // The I2C IP has no SMBSUS interrupt; SMBUS_STATUS.SMBSUS is the only observe path.
    return false;
}

/**
 * @brief Clear SMBus Suspend interrupt
 *
 * @param idx I2C instance index
 */
static void smbus_clear_suspend_irq(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t intr_clear = {.w = 0};
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_clear.w);
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t CONTROLLER_IDX =
        0; // I2C_0 as Controller/Host (detects SMBALERT# and performs ARA)
    const uint8_t SLAVE_ADDR = 0x40; // External SV model address (7-bit) - matches pmbus_slave_i2c0
    uint32_t base;                   // I2C base address (used throughout the function)
    int ret;

    //-------------//
    // RESET & PLL //
    //-------------//
    simputs("\n");
    simputs("################################################\n");
    simputs("##  I2C SMBus Alert/Suspend Test             ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("[MAIN] Firmware main() started\n");
    simputs("[MAIN] Test initialization complete\n");

    //=========================================================================
    // Step 1: System Initialization
    //=========================================================================
    simputs("[MAIN] Entering Step 1: System Initialization\n");
    write_scratch(0, 0x00000010);
    write_scratch(1, 0x00000010);
    simputs("[MAIN] Step 1 marker written (scratch[0]=0x10, scratch[1]=0x10)\n");
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");
    write_scratch(0, 0x00000011);
    write_scratch(1, 0x00000011);
    simputs("[MAIN] Step 1 completed marker written (scratch[0]=0x11, scratch[1]=0x11)\n");
    simputs("[MAIN] Step 1 completed\n");

    //=========================================================================
    // Step 2: LEVEL 1 - Wrapper Control Enable
    //         Enable GPIO pad mux (MUST be done FIRST)
    //         NOTE: Only I2C_0 enabled as Controller to communicate with external SV model
    //=========================================================================
    simputs("[MAIN] Entering Step 2: LEVEL 1 - Wrapper Control Enable\n");
    write_scratch(0, 0x00000020);
    write_scratch(1, 0x00000020);
    simputs("[MAIN] Step 2 marker written (scratch[0]=0x20, scratch[1]=0x20)\n");
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

    // Enable I2C_0 Wrapper (Controller mode) - for detecting SMBALERT# and ARA read
    // External SV model (pmbus_slave_i2c0 @ 0x40) acts as Target/Device
    simputs("[MAIN] Calling i2c_wrapper_enable(CONTROLLER_IDX=0, true)...\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    simputs("[MAIN] i2c_wrapper_enable() returned\n");

    write_scratch(0, 0x00000021);
    write_scratch(1, 0x00000021);
    simputs("[MAIN] Step 2 completed marker written (scratch[0]=0x21, scratch[1]=0x21)\n");
    simputs("[MAIN] Step 2 completed\n");

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
    //=========================================================================
    simputs("[MAIN] Entering Step 3: LEVEL 2 - I2C IP Initialization\n");
    write_scratch(0, 0x00000030);
    write_scratch(1, 0x00000030);
    simputs("[MAIN] Step 3 marker written (scratch[0]=0x30, scratch[1]=0x30)\n");
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    // Compute optimal timing parameters
    i2c_timing_physical_t physical_params = {
        .speed = I2C_SPEED_STANDARD, // 100 kHz
        .clock_period_nanos = 5,     // 200 MHz peripheral clock
        .sda_rise_nanos = 300,       // Typical for 4.7k pullup
        .sda_fall_nanos = 100,       // Typical fall time
        .scl_period_nanos = 0        // Auto
    };

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    // Initialize I2C_0 as Controller (detects SMBALERT# and performs ARA read)
    // External SV model (pmbus_slave_i2c0 @ 0x40) acts as Target/Device
    simputs("  Initializing I2C_0 Controller...\n");
    simputshex32("  External SV model address: 0x", (uint32_t)SLAVE_ADDR);
    simputs(" (pmbus_slave_i2c0)\n");

    i2c_controller_config_t ctrlr_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH,
                 .fmt_thresh = I2C_DEFAULT_FMT_THRESH,
                 .tx_thresh = 0,
                 .acq_thresh = 0},
        .enable_interrupts =
            false, // We use polling, but will enable SMBus alert interrupt separately
        .timeout_cycles = 0};

    simputs("[MAIN] Calling i2c_controller_init(CONTROLLER_IDX=0, &ctrlr_cfg)...\n");
    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    simputs("[MAIN] i2c_controller_init() returned, ret=");
    simputshex32("", (uint32_t)ret);
    simputs("\n");
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("[MAIN] Controller initialized successfully\n");

    // Enable SMBus Alert interrupt for Controller mode
    base = i2c_get_base(CONTROLLER_IDX);
    i2c__INTR_ENABLE_t intr_en = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr_en.f.SMBALERT = 1; // Enable SMBus Alert interrupt
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_en.w);
    simputs("[MAIN] SMBus Alert interrupt enabled\n");

    simputs("  Controller initialized successfully\n");
    simputs("  External SV model (pmbus_slave_i2c0 @ 0x40) ready as Target\n");

    write_scratch(0, 0x00000031);
    write_scratch(1, 0x00000031);
    simputs("[MAIN] Step 3 completed marker written (scratch[0]=0x31, scratch[1]=0x31)\n");
    simputs("[MAIN] Step 3 completed\n");

    //=========================================================================
    // Step 4: Test SMBus Alert (Device -> Host)
    //         NOTE: External SV model (pmbus_slave_i2c0) will assert SMBALERT#
    //         I2C_0 Controller will detect the alert and perform ARA read
    //=========================================================================
    simputs("[MAIN] Entering Step 4: Test SMBus Alert (Device -> Host)\n");
    write_scratch(0, 0x00000040);
    write_scratch(1, 0x00000040);
    simputs("[MAIN] Step 4 marker written (scratch[0]=0x40, scratch[1]=0x40)\n");
    simputs("\nStep 4: Test SMBus Alert (Device -> Host)\n");
    simputs("  NOTE: External SV model (pmbus_slave_i2c0 @ 0x40) will assert SMBALERT#\n");
    simputs("  I2C_0 Controller will detect alert and perform ARA read\n");

    // Clear initial state
    simputs("[MAIN] Clearing initial alert state...\n");
    smbus_clear_alert_irq(CONTROLLER_IDX);
    simputs("[MAIN] Initial alert state cleared\n");
    simputs("  Initial state cleared (ALERT=0)\n");

    // Wait for external SV model to assert SMBALERT#
    // NOTE: SV model can assert alert via assert_alert task or internal logic
    // Give Cocotb time to trigger alert after seeing Step 4 marker
    simputs("[MAIN] Waiting for external SV model to assert SMBALERT#...\n");
    simputs("  [ALERT] Waiting for external SV model to assert SMBALERT#...\n");
    simputs("  [ALERT] (SV model should assert alert via assert_alert task or internal logic)\n");
    simputs("[MAIN] Giving Cocotb time to trigger alert (waiting 10000 cycles)...\n");
    for (volatile uint32_t i = 0; i < 10000; i++)
        ; // ~100us @ 100MHz - give Cocotb time to trigger
    simputs("[MAIN] Wait loop completed, checking alert status...\n");

    // Check current alert status
    bool initial_alert_status = smbus_get_alert_status(CONTROLLER_IDX);
    simputs("  [ALERT] Initial Host alert status: ");
    simputs(initial_alert_status ? "ACTIVE (1)" : "INACTIVE (0)");
    simputs("\n");

    // ======================================================================
    // Checker 1-2: Detect SMBALERT# (HW) and update SMBUS_STATUS
    // ======================================================================
    simputs("[MAIN] Starting wait_until() for alert status (timeout=50000 cycles)...\n");
    simputs("  [ALERT] Waiting for Host (I2C_0 Controller) to detect alert...\n");

    if (!wait_until(smbus_get_alert_status, CONTROLLER_IDX, true, 50000)) {
        simputs("[MAIN] wait_until() TIMEOUT - alert status not detected!\n");
        simputs("  ERROR: SMBus ALERT did not propagate Device->Host\n");
        simputs("  [CHECKER 1 FAILED] DUT did not detect SMBALERT# signal\n");
        simputs("  [CHECKER 2 FAILED] SMBUS_STATUS register was not updated\n");

        // DEBUG: Check final status and configuration
        i2c__SMBUS_STATUS_t final_smbus_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        simputs("  [DEBUG] Final SMBUS_STATUS: val=0x");
        simputshex32("", final_smbus_status.w);
        simputs(", smbalert=");
        simputshex32("", final_smbus_status.f.SMBALERT ? 1 : 0);
        simputs("\n");
        simputs("  [DEBUG] Final Host alert status: ");
        bool final_status = smbus_get_alert_status(CONTROLLER_IDX);
        simputs(final_status ? "ACTIVE (1)" : "INACTIVE (0)");
        simputs("\n");
        simputs("  [DEBUG] Check if SV model (pmbus_slave_i2c0) has asserted SMBALERT#\n");
        simputs("  [DEBUG] Check if I2C controller is in Controller mode (ENABLEHOST=1)\n");
        simputs("  [DEBUG] Check if SMBUS_STATUS register is being read correctly\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    simputs("  [CHECKER 1 PASSED] DUT detected SMBALERT# signal (hardware)\n");
    simputs("  [CHECKER 2 PASSED] SMBUS_STATUS register updated (hardware)\n");
    simputs("  [ALERT] Host detected alert status successfully\n");

    // ======================================================================
    // Checker 3: Trigger alert interrupt (HW)
    // Checker 4: Firmware detects alert status
    // Checker 5: Firmware detects alert interrupt
    // ======================================================================
    // These two checkers assert an interrupt fact, so they wait on INTR_STATE.
    // smbus_get_alert_status() reads only SMBUS_STATUS -- the predicate
    // CHECKERs 1/2 have just satisfied -- and would return immediately on a
    // DUT whose SMBALERT interrupt never fired.
    if (!wait_until(smbus_intr_alert_only, CONTROLLER_IDX, true, 50000)) {
        simputs("  ERROR: INTR_STATE.SMBALERT never asserted on Host\n");
        simputs("  [CHECKER 3 FAILED] Alert interrupt was not triggered (hardware)\n");
        simputs("  [CHECKER 5 FAILED] Firmware did not detect alert interrupt\n");

        // DEBUG: Check both INTR_STATE and SMBUS_STATUS
        uint32_t base = i2c_get_base(CONTROLLER_IDX);
        i2c__INTR_STATE_t intr_state = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__SMBUS_STATUS_t smbus_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        simputs("  [DEBUG] INTR_STATE.SMBALERT=");
        simputs(intr_state.f.SMBALERT ? "1" : "0");
        simputs(", SMBUS_STATUS.SMBALERT=");
        simputs(smbus_status.f.SMBALERT ? "1" : "0");
        simputs("\n");

        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    simputs("  [CHECKER 3 PASSED] Alert interrupt triggered (hardware)\n");
    simputs("  [CHECKER 4 PASSED] Firmware detected alert status\n");
    simputs("  [CHECKER 5 PASSED] Firmware detected alert interrupt\n");
    simputs("  [ALERT] Observed Host status=1 and IRQ asserted\n");

    // ======================================================================
    // Checker 6: Firmware performs ARA read (0x0C)
    // ======================================================================
    simputs("  [ALERT] Host performing ARA read (0x0C)...\n");
    simputs("  [ALERT] Using SMBUS_ADDR_ARA=0x0C for ARA read\n");
    uint8_t alert_addr = 0;
    ret = smbus_alert_response(CONTROLLER_IDX, &alert_addr);
    simputs("  [ALERT] ARA read completed, ret=");
    simputshex32("", (uint32_t)ret);
    simputs("\n");

    // Checker 6: ARA read must succeed
    if (ret != I2C_OK) {
        simputs("  ERROR: ARA read failed (ret=");
        simputshex32("", (uint32_t)ret);
        simputs(")\n");
        simputs("  [CHECKER 6 FAILED] Firmware failed to execute ARA read\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }
    simputs("  [CHECKER 6 PASSED] ARA read executed successfully\n");

    // ======================================================================
    // Checker 7: Receive model response (0x80 = 0x40 << 1)
    // Checker 8: Extract alerting device address (0x40)
    // ======================================================================
    simputshex32("  [ALERT] ARA response address: ", (uint32_t)alert_addr);
    simputs("\n");

    // Checker 7 & 8: Verify response address
    // Expected: response_byte = 0x80, alert_addr = 0x40
    const uint8_t EXPECTED_ALERT_ADDR = 0x40; // pmbus_slave_i2c0 address
    if (alert_addr != EXPECTED_ALERT_ADDR) {
        simputs("  ERROR: ARA response address mismatch\n");
        simputs("  [CHECKER 7/8 FAILED] Expected alert_addr=0x");
        simputshex32("", (uint32_t)EXPECTED_ALERT_ADDR);
        simputs(", got 0x");
        simputshex32("", (uint32_t)alert_addr);
        simputs("\n");
        // Debug output enabled on error
        simputs("  [DEBUG] Expected response_byte=0x80 (0x40 << 1), extracted addr=0x40\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }
    simputs("  [CHECKER 7 PASSED] Received Model response (0x80 = 0x40 << 1)\n");
    simputs("  [CHECKER 8 PASSED] Extracted alerting device address (0x40)\n");

    // ======================================================================
    // Checker 9: Model auto-deasserts alert
    // Checker 10: Firmware detects alert cleared
    // ======================================================================
    simputs("  [ALERT] Waiting for Model to deassert alert after ARA read...\n");
    if (!wait_until(smbus_get_alert_status, CONTROLLER_IDX, false, 50000)) {
        simputs("  ERROR: SMBus ALERT did not clear after ARA read\n");
        simputs("  [CHECKER 9 FAILED] Model did not deassert alert after ARA\n");
        simputs("  [CHECKER 10 FAILED] Firmware did not detect alert cleared\n");
        simputs("  [DEBUG] Final alert status: ");
        bool final_alert_status = smbus_get_alert_status(CONTROLLER_IDX);
        simputs(final_alert_status ? "ACTIVE (1)" : "INACTIVE (0)");
        simputs("\n");
        write_scratch(0, 0xBAD00044);
        test_fail(0);
    }
    simputs("  [CHECKER 9 PASSED] Model automatically deasserted alert\n");
    simputs("  [CHECKER 10 PASSED] Firmware detected alert cleared\n");

    // ======================================================================
    // Checker 11: Firmware clears interrupt
    //
    // Both legs, on INTR_STATE: SMBUS_STATUS is what CHECKER 10 has just
    // established and nothing in between can change it, so a wait on it would
    // return on its first iteration whatever the write-1-to-clear did.
    // ======================================================================
    if (!smbus_intr_alert_only(CONTROLLER_IDX)) {
        simputs("  ERROR: INTR_STATE.SMBALERT not set before the clear\n");
        simputs("  [CHECKER 11 FAILED] no pending interrupt to clear -- a clear\n");
        simputs("           that starts from 0 proves nothing about W1C\n");
        write_scratch(0, 0xBAD00046);
        test_fail(0);
    }
    simputs("  [ALERT] INTR_STATE.SMBALERT pending; clearing alert interrupt...\n");
    smbus_clear_alert_irq(CONTROLLER_IDX);
    if (!wait_until(smbus_intr_alert_only, CONTROLLER_IDX, false, 50000)) {
        simputs("  ERROR: INTR_STATE.SMBALERT still set after write-1-to-clear\n");
        simputs("  [CHECKER 11 FAILED] Firmware failed to clear interrupt\n");
        write_scratch(0, 0xBAD00045);
        test_fail(0);
    }
    simputs("  [CHECKER 11 PASSED] INTR_STATE.SMBALERT observed set, then cleared\n");

    // NOTE: External SV model will deassert alert after ARA read
    simputs("  [ALERT] Host performed ARA read; SV model should deassert alert\n");

    write_scratch(0, 0x00000041);
    write_scratch(1, 0x00000041);

    //=========================================================================
    // Step 5: Test SMBus Suspend (Host -> Device)
    //         NOTE: I2C_0 Controller asserts SMBSUS#
    //         (stimulus only -- the SV model does not sample SMBSUS#)
    //=========================================================================
    write_scratch(0, 0x00000050);
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Test SMBus Suspend (Host -> Device)\n");
    simputs("  NOTE: I2C_0 Controller asserts SMBSUS#\n");
    // No suspend verdict is printed below: the SMBus peer hardwires
    // SMBSUS_N = 1'bz (tb_uvm/sv/I2C_SMBUS_MODEL.sv) and samples it nowhere, so
    // nothing in this configuration can observe whether the device saw the
    // suspend. The stimulus stays; the claim does not.
    simputs("  NOTE: the SV model does not sample SMBSUS#, so this step is\n");
    simputs("        stimulus only -- it is not checked and not reported\n");

    // Clear initial state
    i2c_smbus_suspend(CONTROLLER_IDX, false); // Ensure suspend is deasserted
    simputs("  Initial state cleared (SUSPEND=0)\n");

    // Host asserts SUSPEND
    simputs("  [SUSPEND] Host (I2C_0 Controller) asserts SMBSUS#\n");
    i2c_smbus_suspend(CONTROLLER_IDX, true);
    simputs("  [SUSPEND] SMBSUS# asserted (external SV model should detect)\n");

    // Wait a bit for signal propagation
    for (volatile int i = 0; i < 10000; i++)
        ;

    // Host deasserts SUSPEND
    i2c_smbus_suspend(CONTROLLER_IDX, false);
    simputs("  [SUSPEND] SMBSUS# deasserted\n");

    write_scratch(0, 0x00000051);
    write_scratch(1, 0x00000051);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    write_scratch(0, 0x00000090);
    write_scratch(1, 0x00000090);

    // Signal setup complete to testbench
    write_scratch(0, 0xEBEDEBE4);
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputs("  - I2C_0 (Controller): @ 0xC0009000\n");
    simputshex32("  - External SV model:  Addr 0x", (uint32_t)SLAVE_ADDR);
    simputs(" (pmbus_slave_i2c0)\n");
    simputs("  - SMBus Alert:        PASS\n");
    simputs("  - SMBus Suspend:      driven, not observable (see Step 5)\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
