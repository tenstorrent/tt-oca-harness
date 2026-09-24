/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C Read Sanity Test - controller reads pre-loaded target TX data
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
 *     * THIGH: 0x1A (SCL high period)
 *     * TLOW:  0x32 (SCL low period)
 *     * T_R:   0x02 (rise time)
 *     * T_F:   0x02 (fall time)
 *   - Control Register (0xC0009010):
 *     * ENABLETARGET = 1 (enable target mode)
 *
 * I2C_1 Configuration (Controller Mode):
 *   - FIFO Thresholds:
 *     * RX FIFO:  29 entries (received data)
 *     * FMT FIFO: 5 entries (format/command queue)
 *   - Timing: Default (Standard mode, 100 kHz)
 *   - Control Register (0xC0009210):
 *     * ENABLEHOST = 1 (enable controller/host mode)
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 *   - Note: Clock and peripheral initialization handled by testbench
 *
 * Step 2: LEVEL 1 - Wrapper Control Enable
 *   - Enable I2C_0 Wrapper (0xC0009E00): Target mode
 *     Write: 0x01 (I2C_EN=1, I2C_CONTROLLER_MODE_EN=0)
 *   - Enable I2C_1 Wrapper (0xC0009E04): Controller mode
 *     Write: 0x11 (I2C_EN=1, I2C_CONTROLLER_MODE_EN=1)
 *
 * Step 3: LEVEL 2 - I2C IP Initialization
 *   - Initialize I2C_0 as Target:
 *     1. Reset FIFOs (ACQRST=1, TXRST=1)
 *     2. Configure timing parameters (5 registers: TIMING0-4)
 *     3. Set target address (TARGET_ID register)
 *     4. Configure FIFO thresholds (TARGET_FIFO_CONFIG)
 *     5. Enable target mode (CTRL.ENABLETARGET=1)
 *   - Initialize I2C_1 as Controller:
 *     1. Reset FIFOs (RXRST=1, FMTRST=1)
 *     2. Configure timing parameters (same as target)
 *     3. Configure FIFO thresholds (HOST_FIFO_CONFIG)
 *     4. Enable controller mode (CTRL.ENABLEHOST=1)
 *
 * Step 4: Prepare Target TX FIFO
 *   - Pre-load TX FIFO with response data for each transaction
 *   - Data will be sent when Controller reads
 *
 * Step 5: I2C Communication Test
 *   - Controller Read Transaction (I2C_1 <- I2C_0):
 *     1. Controller reads from target address (0x10)
 *     2. Target responds via TX FIFO with pre-loaded data
 *     3. Controller receives data in RX FIFO
 *
 * Step 6: Data Verification
 *   - Compare received data with expected data
 *   - Report any mismatches
 *
 * =============================================================================
 * FIFO Details
 * =============================================================================
 *
 * Target Mode FIFOs (I2C_0):
 *   - ACQ FIFO (Acquisition FIFO):
 *     * Depth: 64 entries
 *     * Threshold: 29 (interrupt when ≥29 entries)
 *     * Format: {signal[2:0], abyte[7:0]}
 *     * Signals: START(1), STOP(2), RESTART(3), DATA(0)
 *   - TX FIFO (Transmit FIFO):
 *     * Depth: 32 entries
 *     * Threshold: 5 (interrupt when ≤5 entries)
 *     * Used for target->controller data transfer
 *
 * Controller Mode FIFOs (I2C_1):
 *   - FMT FIFO (Format FIFO):
 *     * Depth: 32 entries
 *     * Threshold: 5 (interrupt when ≤5 entries)
 *     * Format: {fbyte[7:0], flags[7:0]}
 *     * Flags: START, STOP, READB, RCONT, NAKOK
 *   - RX FIFO (Receive FIFO):
 *     * Depth: 32 entries
 *     * Threshold: 29 (interrupt when ≥29 entries)
 *     * Stores data received from target
 *
 * =============================================================================
 * Test Data
 * =============================================================================
 *
 * Test Payload: 4 bytes per transaction
 *   {0xAC, 0x8F, 0x73, 0xB2}
 *
 * Multiple transactions with unique patterns
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
 * @brief Print complete FIFO status for debugging
 *
 * This function prints all relevant FIFO and status information
 * for both Controller and Target modes.
 *
 * @param controller_idx Controller I2C instance index
 * @param target_idx Target I2C instance index
 * @param label Label string for this status dump
 */
static void print_complete_fifo_status(uint32_t controller_idx, uint32_t target_idx,
                                       const char *label) {
    simputs("  [FIFO_STATUS] ");
    simputs(label);
    simputs("\n");

    // Controller Status
    {
        uint32_t base = i2c_get_base(controller_idx);
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__HOST_FIFO_STATUS_t fifo_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        simputs("    Controller[");
        simputshex32("", controller_idx);
        simputs("]:\n");
        simputs("      CTRL: enablehost=");
        simputshex32("", ctrl.f.ENABLEHOST);
        simputs(", enabletarget=");
        simputshex32("", ctrl.f.ENABLETARGET);
        simputs("\n");
        simputs("      STATUS: hostidle=");
        simputshex32("", status.f.HOSTIDLE);
        simputs(", fmtfull=");
        simputshex32("", status.f.FMTFULL);
        simputs(", fmtempty=");
        simputshex32("", status.f.FMTEMPTY);
        simputs(", rxfull=");
        simputshex32("", status.f.RXFULL);
        simputs(", rxempty=");
        simputshex32("", status.f.RXEMPTY);
        simputs("\n");
        simputs("      FIFO: fmtlvl=");
        simputshex32("", fifo_status.f.FMTLVL);
        simputs(", rxlvl=");
        simputshex32("", fifo_status.f.RXLVL);
        simputs("\n");
    }

    // Target Status
    {
        uint32_t base = i2c_get_base(target_idx);
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__TARGET_FIFO_STATUS_t fifo_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        simputs("    Target[");
        simputshex32("", target_idx);
        simputs("]:\n");
        simputs("      CTRL: enablehost=");
        simputshex32("", ctrl.f.ENABLEHOST);
        simputs(", enabletarget=");
        simputshex32("", ctrl.f.ENABLETARGET);
        simputs("\n");
        simputs("      STATUS: targetidle=");
        simputshex32("", status.f.TARGETIDLE);
        simputs(", acqfull=");
        simputshex32("", status.f.ACQFULL);
        simputs(", acqempty=");
        simputshex32("", status.f.ACQEMPTY);
        simputs(", txfull=");
        simputshex32("", status.f.TXFULL);
        simputs(", txempty=");
        simputshex32("", status.f.TXEMPTY);
        simputs("\n");
        simputs("      FIFO: txlvl=");
        simputshex32("", fifo_status.f.TXLVL);
        simputs(", acqlvl=");
        simputshex32("", fifo_status.f.ACQLVL);
        simputs("\n");
    }
}

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

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t TARGET_IDX = 0;     // I2C_0 as Target
    const uint32_t CONTROLLER_IDX = 1; // I2C_1 as Controller
    const uint8_t TARGET_ADDR = 0x10;  // Target address (7-bit)
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##    I2C Read Sanity Test - Concise Version  ##\n");
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
        .clock_period_nanos = 5, // 200 MHz peripheral clock
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

    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
                                   .mask0 = 0x7F, // Exact match
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = computed_timing, // Use computed timing
                                   .fifo = {.tx_thresh = I2C_DEFAULT_TX_THRESH,
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

    // Explicitly set ACQ_START_STOP_EN bit to 1
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    // 3b. Initialize I2C_1 as Controller
    simputs("  Initializing I2C_1 Controller...\n");

    // Controller uses the same computed timing parameters
    i2c_controller_config_t ctrlr_cfg = {.timing =
                                             computed_timing, // Use same computed timing as target
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
    // Step 4: Multiple I2C Read Communication Tests
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Multiple I2C Read Communication Tests\n");

    // Define number of transactions to test
    const uint32_t NUM_TRANSACTIONS = 2;

    // Test data patterns
    unsigned char test_data_base[] = {0xAC, 0x8F, 0x73, 0xB2};
    uint32_t data_size = sizeof(test_data_base);

    // Allocate buffers for multiple transactions
    unsigned char test_data[NUM_TRANSACTIONS][4];   // Expected data (what Target sends)
    unsigned char recv_buffer[NUM_TRANSACTIONS][4]; // Received data (what Controller reads)

    // Prepare test data with unique patterns for each transaction
    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        for (uint32_t i = 0; i < data_size; i++) {
            // Add transaction number to make each pattern unique
            test_data[txn][i] = test_data_base[i] ^ (txn & 0xFF);
        }
    }

    //-------------------------------------------------------------------------
    // Step 4: I2C Read Test
    //         Pre-load Target TX FIFO, then Controller reads
    //-------------------------------------------------------------------------
    write_scratch(1, 0x00000041);

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        // CRITICAL: Reset ACQ FIFO before each transaction to prevent stretch_tx
        // According to OpenTitan standard, ACQ FIFO must be empty before read request
        // If ACQ FIFO depth > 1 when read request arrives, stretch_tx will be triggered
        i2c_reset_fifos(TARGET_IDX, false, false, false, true);

        // Clear any unhandled TARGET_EVENTS that might cause stretch_tx
        uint32_t target_events = i2c_get_target_events(TARGET_IDX);
        if (target_events != 0) {
            i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF); // Clear all events
        }

        // Verify ACQ FIFO is empty after reset
        if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
            uint32_t drain_base = i2c_get_base(TARGET_IDX);
            while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            }
        }

        // Pre-load TX FIFO BEFORE read request arrives
        // When Controller sends read request, Target FSM immediately reads from TX FIFO
        // If TX FIFO is empty, Target sends 0xFF (default value)
        uint32_t bytes_sent = i2c_target_transmit(TARGET_IDX, test_data[txn], data_size);
        if (bytes_sent != data_size) {
            simputs("  ERROR: Failed to pre-load TX FIFO at txn ");
            simputshex32("", txn);
            simputs("\n");
            write_scratch(0, 0xBAD00040 | (txn & 0xFF));
            test_fail(0);
        }

        // Controller reads data from Target
        ret = i2c_controller_read(CONTROLLER_IDX, TARGET_ADDR, recv_buffer[txn], data_size, true);
        if (ret != I2C_OK) {
            simputs("  ERROR: Controller read failed at txn ");
            simputshex32("", txn);
            simputs(" with error code ");
            simputshex32("", ret);
            simputs("\n");
            write_scratch(0, 0xBAD00042 | (txn & 0xFF));
            test_fail(0);
        }

        // CRITICAL: Drain Target ACQ FIFO after read operation
        // Pure read operations leave ACQ FIFO entries (START + ADDRESS + READ_BIT)
        // These must be drained to prevent stretch_tx in next transaction
        uint32_t target_base = i2c_get_base(TARGET_IDX);
        uint32_t drain_timeout = 1000;
        while (drain_timeout > 0 && !i2c_target_acq_fifo_empty(TARGET_IDX)) {
            (void)read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            drain_timeout--;
        }

        // i2c_controller_read() returns before the controller is idle (i2c_controller_write()
        // waits internally); wait here so the STOP completes before the next transaction.
        ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) {
            simputs("  ERROR: Wait for controller idle failed at txn ");
            simputshex32("", txn);
            simputs(" with error code ");
            simputshex32("", ret);
            simputs("\n");
            write_scratch(0, 0xBAD00041 | (txn & 0xFF));
            test_fail(0);
        }
    }

    simputs("  All transactions read successfully\n");
    write_scratch(1, 0x00000043);

    //=========================================================================
    // Step 5: Data Verification (All Transactions)
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Data Verification for All Transactions\n");

    uint32_t total_errors = 0;

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        // Compare data byte by byte
        for (uint32_t i = 0; i < data_size; i++) {
            if (recv_buffer[txn][i] != test_data[txn][i]) {
                simputs("  ERROR: Txn ");
                simputshex32("", txn);
                simputs(" Byte[");
                simputshex32("", i);
                simputs("] mismatch: expected 0x");
                simputshex32("", test_data[txn][i]);
                simputs(", got 0x");
                simputshex32("", recv_buffer[txn][i]);
                simputs("\n");
                total_errors++;
            }
        }
    }

    if (total_errors > 0) {
        simputshex32("  TOTAL ERRORS: ", total_errors);
        simputs("\n");
        write_scratch(0, 0xBAD00050 | (total_errors & 0xFF));
        test_fail(0);
    }

    simputs("  All transactions verified successfully!\n");
    write_scratch(1, 0x00000051);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    write_scratch(1, 0x00000090);

    // Final DONE marker for the testbench
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputs("  - I2C_0 (Target):     Addr 0x10 @ 0xC0009000\n");
    simputs("  - I2C_1 (Controller): @ 0xC0009200\n");
    simputshex32("  - Total transactions: ", NUM_TRANSACTIONS);
    simputs("\n");
    simputshex32("  - Bytes per txn:      ", data_size);
    simputs("\n");
    uint32_t total_bytes = NUM_TRANSACTIONS * data_size;
    simputshex32("  - Total bytes:        ", total_bytes);
    simputs("\n");
    simputs("  - Verification:       PASS\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
