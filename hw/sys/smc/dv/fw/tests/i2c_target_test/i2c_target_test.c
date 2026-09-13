/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C Target Test - External Master VIP Test
 *
 * =============================================================================
 * Test Purpose
 * =============================================================================
 *
 * This test verifies I2C Target (Slave) mode functionality:
 *   - Configure I2C_0 as Target mode with address 0x10
 *   - Receive data from external I2C Master (cocotbext-i2c VIP in testbench)
 *   - Verify received data integrity (0xCA, 0xFE, 0x5A, 0x5A)
 *   - Check FIFO values after reception
 *   - Respond to read request with data (0xCA, 0xFE, 0x5A, 0x4B)
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
 *   - Enable Target mode reception
 *   - Handle ACQ FIFO for receiving data
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
 *    - Set Target address to 0x10
 *    - Configure timing and FIFO thresholds
 *    - Enable Target mode
 *
 * 4. Wait for External Master Transaction
 *    - Testbench VIP sends: length header + test data
 *    - Format: [length_byte] [data_byte_0] ... [data_byte_n]
 *
 * 5. Receive and Verify Data
 *    - Parse ACQ FIFO entries
 *    - Extract data bytes
 *    - Verify data integrity
 *    - Check FIFO levels
 *
 * 6. Wait for Read Request
 *    - Detect read request from external master
 *    - Send response data (0xCA, 0xFE, 0x5A, 0x4B)
 *    - Wait for STOP condition
 *
 * =============================================================================
 * Expected Data Format (from VIP)
 * =============================================================================
 *
 * Transaction format:
 *   START + ADDRESS(0x10) + [length] + [data...] + STOP
 *
 * Test data: {0xCA, 0xFE, 0x5A, 0x5A} (4 bytes)
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

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

/**
 * @brief Print Target FIFO status
 *
 * @param idx I2C instance index
 * @param label Label string for this status dump
 */
static void print_target_fifo_status(uint32_t idx, const char *label) {
    uint32_t base = i2c_get_base(idx);
    i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__TARGET_FIFO_STATUS_t fifo_status = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    simputs("  [FIFO_STATUS] ");
    simputs(label);
    simputs("\n");
    simputs("    Target[");
    simputshex32("", idx);
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

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t TARGET_IDX = 0;    // I2C_0 as Target
    const uint8_t TARGET_ADDR = 0x10; // Target address (7-bit)
    int ret;

    //-------------//
    // RESET & PLL //
    //-------------//

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C Target Test                     ##\n");
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
    // Addresses 0x00-0x07 and 0x78-0x7F are reserved per I2C specification
    if (TARGET_ADDR < 0x08 || TARGET_ADDR > 0x77) {
        simputs("  ERROR: Invalid I2C target address\n");
        simputshex32("  Address 0x", TARGET_ADDR);
        simputs(" is outside valid range (0x08-0x77)\n");
        simputs("  Addresses 0x00-0x07 and 0x78-0x7F are reserved\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    // Initialize I2C_0 as Target (address 0x10)
    simputshex32("  Initializing I2C_0 Target (addr=0x", TARGET_ADDR);
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

    // Validate secondary address if used (address1 != 0)
    // A non-zero secondary address must lie in the same 0x08-0x77 range
    const uint8_t TARGET_ADDR1 = 0; // Secondary address (not used in this test)
    if (TARGET_ADDR1 != 0 && (TARGET_ADDR1 < 0x08 || TARGET_ADDR1 > 0x77)) {
        simputs("  ERROR: Invalid I2C secondary target address\n");
        simputshex32("  Address1 0x", TARGET_ADDR1);
        simputs(" is outside valid range (0x08-0x77)\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F, // Exact match
        .address1 = TARGET_ADDR1,
        .mask1 = 0,
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
    write_scratch(1, 0x00000031);

    // Explicitly set ACQ_START_STOP_EN bit to 1
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.w |= (1 << 7); // Set ACQ_START_STOP_EN bit (bit 7)
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    // Reset FIFOs after enabling target mode (OpenTitan best practice)
    // This ensures FIFOs are clean right before use, clearing any stale data
    // that might have accumulated during initialization
    i2c_reset_fifos(TARGET_IDX, false, false, true, true);
    simputs("  FIFOs reset after target enable (OpenTitan pattern)\n");

    // Signal setup done to testbench
    write_scratch(1, 0xEBEDEBE2);
    simputs("  Setup complete - waiting for external master...\n");

    //=========================================================================
    // Step 4: Receive Transaction from External Master
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Receiving I2C Transaction from External Master\n");

    unsigned char recv_buffer[256];
    uint32_t received_len = 0;

    // Wait for and receive transaction from external master (VIP)
    ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer, sizeof(recv_buffer),
                                         &received_len, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    simputshex32("  Received ", received_len);
    simputs(" bytes from external master\n");
    write_scratch(1, 0x00000041);

    // Get FIFO levels for verification
    uint32_t tx_level = 0;
    uint32_t acq_level = 0;
    i2c_target_get_fifo_status(TARGET_IDX, &tx_level, &acq_level);
    simputs("  FIFO Levels: TX=");
    simputshex32("", tx_level);
    simputs(", ACQ=");
    simputshex32("", acq_level);
    simputs("\n");

    //=========================================================================
    // Step 5: Data Verification
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Data Verification\n");

    // Expected data from VIP: {0xCA, 0xFE, 0x5A, 0x5A}
    unsigned char expected_data[] = {0xCA, 0xFE, 0x5A, 0x5A};
    uint32_t expected_len = sizeof(expected_data);

    // Check length
    if (received_len != expected_len) {
        simputs("  ERROR: Length mismatch! Expected ");
        simputshex32("", expected_len);
        simputs(", got ");
        simputshex32("", received_len);
        simputs("\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }

    // Compare data byte by byte
    bool data_mismatch = false;
    for (uint32_t i = 0; i < expected_len; i++) {
        if (recv_buffer[i] != expected_data[i]) {
            simputs("  ERROR: Byte[");
            simputshex32("", i);
            simputs("] mismatch: expected 0x");
            simputshex32("", expected_data[i]);
            simputs(", got 0x");
            simputshex32("", recv_buffer[i]);
            simputs("\n");
            data_mismatch = true;
        }
        // Write each received byte to scratch for debugging
        write_scratch(1, recv_buffer[i]);
    }

    if (data_mismatch) {
        write_scratch(0, 0xBAD00051);
        test_fail(0);
    }

    simputs("  Data verification PASSED\n");
    write_scratch(1, 0x00000051);

    //=========================================================================
    // Step 6: FIFO Verification
    //=========================================================================
    write_scratch(1, 0x00000060);
    simputs("\nStep 6: FIFO Verification\n");

    // After receiving transaction, ACQ FIFO should be empty (all data read)
    // TX FIFO should remain empty (we're not transmitting)
    i2c_target_get_fifo_status(TARGET_IDX, &tx_level, &acq_level);
    simputs("  Final FIFO Levels: TX=");
    simputshex32("", tx_level);
    simputs(", ACQ=");
    simputshex32("", acq_level);
    simputs("\n");

    // Verify ACQ FIFO is empty after reading all data
    if (acq_level != 0) {
        simputs("  WARNING: ACQ FIFO not empty after reading transaction\n");
        simputs("  This may indicate incomplete transaction parsing\n");
    }

    // Verify TX FIFO is empty (we're not transmitting)
    if (tx_level != 0) {
        simputs("  WARNING: TX FIFO not empty (unexpected for receive-only test)\n");
    }

    simputs("  FIFO verification completed\n");
    write_scratch(1, 0x00000061);

    //=========================================================================
    // Step 7: Prepare TX FIFO for Read Response
    //=========================================================================
    write_scratch(1, 0x00000070);
    simputs("\nStep 7: Preparing TX FIFO for Read Response\n");

    // ACQRST empties the ACQ FIFO so acq_fifo_depth_i is 0 before the read request
    // arrives; a software drain can leave entries behind.
    i2c_reset_fifos(TARGET_IDX, false, false, false, true);
    simputs("  ACQ FIFO reset using ACQRST\n");

    // Prepare response data: {0xCA, 0xFE, 0x5A, 0x4B}
    unsigned char response_data[] = {0xCA, 0xFE, 0x5A, 0x4B};
    uint32_t response_len = sizeof(response_data);

    simputs("  Pre-loading TX FIFO with response data: ");
    for (uint32_t i = 0; i < response_len; i++) {
        simputshex32("0x", response_data[i]);
        if (i < response_len - 1) simputs(" ");
    }
    simputs("\n");

    // CRITICAL: Pre-load TX FIFO BEFORE read request arrives
    // When master sends read request, target FSM immediately reads from TX FIFO
    // If TX FIFO is empty, target sends 0xFF (default value)
    uint32_t bytes_sent = i2c_target_transmit(TARGET_IDX, response_data, response_len);
    if (bytes_sent != response_len) {
        simputs("  ERROR: Failed to pre-load TX FIFO\n");
        simputshex32("  Expected: ", response_len);
        simputs(", sent: ");
        simputshex32("", bytes_sent);
        simputs("\n");
        write_scratch(0, 0xBAD00071);
        test_fail(0);
    }

    simputs("  TX FIFO pre-loaded with ");
    simputshex32("", bytes_sent);
    simputs(" bytes\n");

    // Clear any unhandled TARGET_EVENTS that might cause stretch_tx
    // This ensures target FSM can transmit data immediately when read request arrives
    uint32_t target_events = i2c_get_target_events(TARGET_IDX);
    if (target_events != 0) {
        simputs("  Clearing unhandled TARGET_EVENTS: ");
        simputshex32("0x", target_events);
        simputs("\n");
        i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF); // Clear all events
    }

    // ACQRST again: the target FSM (hw/ip/i2c/rtl/i2c_target_fsm.sv) asserts stretch_tx
    // whenever acq_fifo_depth_i > 1, even with acq_fifo_plenty_space set.
    i2c_reset_fifos(TARGET_IDX, false, false, false, true);

    // Verify ACQ FIFO is empty after reset
    if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
        simputs("  WARNING: ACQ FIFO not empty after reset\n");
        // Additional drain attempt if reset didn't work
        while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
            uint32_t drain_base = i2c_get_base(TARGET_IDX);
            (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        }
    }
    simputs("  ACQ FIFO confirmed empty before read request\n");

    // Signal to testbench that TX FIFO is ready for read request
    write_scratch(1, 0xEBEDEBE3);

    // CRITICAL: Do NOT drain ACQ FIFO while waiting for read request
    // The target FSM needs the START entry in ACQ FIFO to properly transition
    // from AddrAckHold to TransmitWait. If we drain ACQ FIFO too early,
    // the FSM may enter WaitForStop instead of TransmitWait.
    // We only monitor targetidle status to detect when read transaction completes.

    uint32_t read_wait_count = 0;
    const uint32_t READ_WAIT_TIMEOUT = I2C_TIMEOUT_DEFAULT;
    bool read_request_detected = false;
    base = i2c_get_base(TARGET_IDX); // Reuse base variable defined earlier

    // Monitor targetidle status to detect read request
    // When read request arrives, targetidle will process it and targetidle will change
    // We wait for targetidle to go from idle (1) to active (0), then back to idle (1)
    bool was_idle = true;
    uint32_t active_count = 0;

    simputs("  Waiting for read request (monitoring targetidle status)...\n");

    while (read_wait_count < READ_WAIT_TIMEOUT) {
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        bool is_idle = status.f.TARGETIDLE;

        // Detect transition from idle to active (read request received)
        if (was_idle && !is_idle) {
            active_count++;
            simputs("  Read request detected (targetidle: idle -> active)\n");
        }

        // Detect transition back to idle (read transaction completed)
        if (!was_idle && is_idle) {
            // Read transaction completed
            read_request_detected = true;
            simputs("  Read transaction completed (targetidle: active -> idle)\n");
            break;
        }

        was_idle = is_idle;

        read_wait_count++;
        if (read_wait_count % 100000 == 0) {
            simputs("  Still waiting for read request...\n");
            for (volatile uint32_t i = 0; i < 1000; i++)
                ;
        }
    }

    if (!read_request_detected) {
        simputs("  ERROR: Timeout waiting for read request\n");
        simputshex32("  Last targetidle status: ", was_idle ? 1 : 0);
        simputs("\n");
        write_scratch(0, 0xBAD00070);
        test_fail(0);
    }

    simputs("  Read request detected, waiting for transaction completion...\n");
    write_scratch(1, 0x00000072);

    // Wait for read transaction completion
    // Read transaction is considered complete when targetidle goes back to idle
    // This indicates the transaction has been processed by the FSM
    uint32_t stop_wait_count = 0;
    const uint32_t STOP_WAIT_TIMEOUT = I2C_TIMEOUT_DEFAULT;
    bool read_complete = false;

    while (stop_wait_count < STOP_WAIT_TIMEOUT) {
        i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        // Read transaction is complete when target returns to idle
        // We don't need to wait for txempty since data may still be in FIFO
        if (status.f.TARGETIDLE) {
            read_complete = true;
            simputs("  Read transaction completed (targetidle=1)\n");
            break;
        }

        stop_wait_count++;
        if (stop_wait_count % 100000 == 0) {
            simputs("  Still waiting for read transaction completion...\n");
            for (volatile uint32_t i = 0; i < 1000; i++)
                ;
        }
    }

    if (!read_complete) {
        simputs("  [ERROR] Timeout waiting for read transaction completion\n");
        write_scratch(0, 0xBAD00078);
        test_fail(0);
    }

    simputs("  Read transaction completion confirmed\n");
    write_scratch(1, 0x00000073);

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
    simputs("  - External Master:    cocotbext-i2c VIP\n");
    simputshex32("  - Bytes received:     ", received_len);
    simputs("\n");
    simputs("  - Write Data:         0xCA 0xFE 0x5A 0x5A\n");
    simputs("  - Read Response:      0xCA 0xFE 0x5A 0x4B\n");
    simputs("  - Verification:       PASS\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
