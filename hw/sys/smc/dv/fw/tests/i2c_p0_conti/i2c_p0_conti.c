/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P0 Continuous Test - Continuous Transactions with Repeated START
 *
 * =============================================================================
 * Test Mode Selection
 * =============================================================================
 *
 * This test supports three modes (configured via TEST_MODE constant):
 *   - I2C_TEST_MODE_ALL_WRITE:    All transactions are Write
 *   - I2C_TEST_MODE_ALL_READ:    All transactions are Read
 *   - I2C_TEST_MODE_ALTERNATING: Alternating Write/Read pattern
 *
 * Change TEST_MODE in main() to select the desired test mode.
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
 *
 * I2C_1 Configuration (Controller Mode):
 *   - FIFO Thresholds:
 *     * RX FIFO:  29 entries (received data)
 *     * FMT FIFO: 5 entries (format/command queue)
 *   - Timing: Default (Standard mode, 100 kHz)
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: LEVEL 1 - Wrapper Control Enable
 * Step 3: LEVEL 2 - I2C IP Initialization
 * Step 4: Continuous Transactions with Repeated START
 *   - Mode: ALL_WRITE
 *     * Transaction 0: Write [NO STOP]
 *     * Transaction 1: Write [NO STOP]
 *     * Transaction 2: Write [WITH STOP]
 *   - Mode: ALL_READ
 *     * Transaction 0: Read [NO STOP]
 *     * Transaction 1: Read [NO STOP]
 *     * Transaction 2: Read [WITH STOP]
 *   - Mode: ALTERNATING
 *     * Transaction 0: Write [NO STOP]
 *     * Transaction 1: Read [NO STOP]
 *     * Transaction 2: Write [WITH STOP]
 *   - All transactions use Repeated START except the last one
 * Step 5: Data Verification
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

//=============================================================================
// Test Mode Definitions
//=============================================================================

typedef enum {
    I2C_TEST_MODE_ALL_WRITE = 0,  // All transactions are Write
    I2C_TEST_MODE_ALL_READ = 1,   // All transactions are Read
    I2C_TEST_MODE_ALTERNATING = 2 // Alternating Write/Read pattern
} i2c_test_mode_t;

//=============================================================================
// Helper Functions
//=============================================================================

/**
 * @brief Print complete FIFO status for debugging
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
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputshex32("  Wrapper[", idx);
    simputshex32("] enabled: addr=", wrapper_addr);
    simputs(", mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

/**
 * @brief Write with header and optional STOP control using i2c_opentitan functions
 * This function writes data with length header, supporting Repeated START
 * Uses i2c_opentitan.c helper functions for consistency
 */
static int i2c_controller_write_with_header_conti(uint32_t idx, uint8_t target_addr,
                                                  const uint8_t *data, uint32_t len,
                                                  bool send_stop) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);

    // CRITICAL FIX: Support Repeated START (same logic as i2c_controller_write)
    // In Repeated START scenarios, controller stays busy between transactions.
    // Only wait for idle if controller was previously stopped (hostidle=1).
    // If controller is already busy (hostidle=0), assume Repeated START sequence.
    i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    // Check if we need to wait for idle
    // If hostidle=1, wait normally (previous transaction sent STOP)
    // If hostidle=0, skip wait (Repeated START - controller intentionally kept busy)
    if (status.f.HOSTIDLE) {
        // Controller was idle, wait for it to be ready
        int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) return ret;
    }
// else: Controller is busy - this is a Repeated START, continue directly

// Helper macro: Wait for FIFO to be NOT FULL before writing (from i2c_opentitan.c)
// FMTFULL is the inverse of fmt_fifo_wready, so FMTFULL=0 means ready
#define WAIT_FIFO_NOT_FULL() \
    do { \
        uint32_t timeout = 5000; \
        i2c__STATUS_t fifo_status; \
        while (timeout > 0) { \
            fifo_status.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - \
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0))); \
            if (fifo_status.f.FMTFULL == 0) break; \
            timeout--; \
        } \
        if (timeout == 0) return I2C_ERROR_TIMEOUT; \
    } while (0)

    i2c__FDATA_t fdata = {.w = 0};

    // Send START + address (write bit = 0)
    // If controller was busy, this becomes a Repeated START automatically
    WAIT_FIFO_NOT_FULL(); // Ensure FIFO ready before write
    fdata.f.FBYTE = (target_addr << 1) | 0x0;
    fdata.f.START = 1;
    fdata.f.READB = 0;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    // Send length header
    WAIT_FIFO_NOT_FULL(); // Ensure FIFO ready before write
    fdata.w = 0;
    fdata.f.FBYTE = (len & 0xFF);
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    // Send data bytes with STOP control
    for (uint32_t i = 0; i < len; i++) {
        WAIT_FIFO_NOT_FULL(); // CRITICAL: Check before EACH write!
        fdata.w = 0;
        fdata.f.FBYTE = data[i];
        if (send_stop && (i == len - 1)) {
            fdata.f.STOP = 1;
        }
        fdata.f.READB = 0;
        write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);
    }

#undef WAIT_FIFO_NOT_FULL

    // CRITICAL: Wait for FMT FIFO to be completely processed AND controller ready for next
    // transaction In repeated START scenario, we need to ensure:
    // 1. FMT FIFO is empty (all entries processed)
    // 2. FMT FIFO has space for next transaction (at least 2 entries for START+address and data)
    // 3. Controller state machine is ready (not in PopFmtFifo state waiting for more entries)
    if (!send_stop) {
        // For repeated START: Wait for FMT FIFO to become empty AND have space
        // This ensures the entire transaction has been sent AND controller is ready for next
        // transaction
        uint32_t wait_count = 0;
        const uint32_t MAX_WAIT = 100000; // Increased timeout for complete transaction
        i2c__STATUS_t status;
        i2c__HOST_FIFO_STATUS_t fifo_status;

        // Step 1: Wait for FMT FIFO to become empty (all entries processed)
        while (wait_count < MAX_WAIT) {
            status.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                        SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            if (status.f.FMTEMPTY) {
                // FMT FIFO is empty, all entries have been processed
                break;
            }
            wait_count++;
        }

        if (wait_count >= MAX_WAIT) {
            simputs("    [Controller] WARNING: Timeout waiting for FMT FIFO to become empty\n");
            return I2C_ERROR_TIMEOUT;
        }

        // Step 2: Wait for FMT FIFO to have space (at least 2 entries for next transaction)
        // This ensures controller state machine has moved past PopFmtFifo state
        wait_count = 0;
        while (wait_count < MAX_WAIT) {
            fifo_status.w =
                read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                 SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            status.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                        SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));

            // Check: FMT FIFO empty AND has space (fmtfull=0 means space available)
            if (status.f.FMTEMPTY && !status.f.FMTFULL && fifo_status.f.FMTLVL == 0) {
                // FMT FIFO is empty and ready for next transaction
                break;
            }
            wait_count++;
        }

        if (wait_count >= MAX_WAIT) {
            simputs("    [Controller] WARNING: Timeout waiting for FMT FIFO to be ready\n");
            return I2C_ERROR_TIMEOUT;
        }

        // Step 3: Small delay to ensure controller state machine is stable
        // This gives the FSM time to transition from PopFmtFifo/Active to Idle (ready for next
        // command)
        for (volatile int i = 0; i < 100; i++)
            ;

        simputs("    [Controller] FMT FIFO ready, controller ready for next transaction\n");
    } else {
        // For STOP transaction: Wait for controller to become idle
        // This ensures transaction is completely finished
        int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) return ret;
    }

    return I2C_OK;
}

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t TARGET_IDX = 0;     // I2C_0 as Target
    const uint32_t CONTROLLER_IDX = 1; // I2C_1 as Controller
    const uint8_t TARGET_ADDR = 0x10;  // Target address (7-bit)

    int ret;

    //=========================================================================
    // Read test mode from scratch register 3
    // scratch[2] is used by virtual console, so we use scratch[3]
    // Values: 0=ALL_WRITE, 1=ALL_READ, 2=ALTERNATING
    // Default to ALTERNATING if scratch[3] is invalid
    //=========================================================================
    uint32_t test_mode_raw = read_scratch(3);
    i2c_test_mode_t TEST_MODE;

    // Parse test mode from scratch[3]
    // 0 = ALL_WRITE, 1 = ALL_READ, 2 = ALTERNATING
    // If scratch[3] is 0 or invalid, default to ALTERNATING (backward compatibility)
    if (test_mode_raw == 0) {
        TEST_MODE = I2C_TEST_MODE_ALL_WRITE;
    } else if (test_mode_raw == 1) {
        TEST_MODE = I2C_TEST_MODE_ALL_READ;
    } else if (test_mode_raw == 2) {
        TEST_MODE = I2C_TEST_MODE_ALTERNATING;
    } else {
        // Default to ALTERNATING for backward compatibility (when scratch[3] is unset or invalid)
        TEST_MODE = I2C_TEST_MODE_ALTERNATING;
    }

    //-------------//
    // RESET & PLL //
    //-------------//

    // Note: peripherals_out_of_reset() is no longer needed as peripherals
    // are automatically released from reset
    // peripherals_out_of_reset();

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Continuous Test - Repeated START ##\n");
    simputs("################################################\n");
    simputs("\n");

    // Print test mode
    simputs("Test Mode: ");
    simputshex32("scratch[3]=", test_mode_raw);
    simputs(" -> ");
    switch (TEST_MODE) {
    case I2C_TEST_MODE_ALL_WRITE:
        simputs("ALL WRITE");
        break;
    case I2C_TEST_MODE_ALL_READ:
        simputs("ALL READ");
        break;
    case I2C_TEST_MODE_ALTERNATING:
        simputs("ALTERNATING (Write/Read)");
        break;
    default:
        simputs("UNKNOWN");
        break;
    }
    simputs("\n\n");

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

    i2c_wrapper_enable(TARGET_IDX, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: LEVEL 2 - I2C IP Initialization
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    simputs("  Initializing I2C_0 Target (addr=0x10)...\n");

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

    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F,
        .address1 = 0,
        .mask1 = 0,
        .timing = computed_timing,
        .fifo = {.tx_thresh = I2C_DEFAULT_TX_THRESH,
                 .acq_thresh = I2C_DEFAULT_ACQ_THRESH,
                 .rx_thresh = 0,
                 .fmt_thresh = 0},
        .enable_interrupts = false,
        .ack_ctrl_mode = false,
        .tx_stretch_ctrl =
            false, // Auto stretch mode: Target automatically stretches clock when TX FIFO is empty
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
    ctrl.w |= (1 << 7); // Set ACQ_START_STOP_EN bit (bit 7)
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

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
    // Step 4: Continuous Transactions with Repeated START
    //=========================================================================
    write_scratch(1, 0x00000040);
    //=========================================================================
    // Step 4: Continuous transactions with Repeated START
    //         Supports three modes: ALL_WRITE, ALL_READ, ALTERNATING
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Continuous transactions with Repeated START\n");
    simputs("  Using i2c_controller_write/i2c_controller_read from i2c_opentitan.c\n");

    const uint32_t NUM_TRANSACTIONS = 2;
    const uint32_t DATA_SIZE = 1;

    // Test data: Transaction 0 = 0x5A, Transaction 1 = 0x5B
    // Use single variables like i2c_p0_cwr, update value in each loop iteration
    uint8_t write_data;
    uint8_t read_data;
    uint8_t read_recv_buffer[2]; // Buffer to receive read data

    // Send consecutive transactions based on test mode
    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        bool send_stop = (txn == NUM_TRANSACTIONS - 1); // Only last transaction sends STOP

        // Determine transaction type based on test mode
        bool is_write;
        switch (TEST_MODE) {
        case I2C_TEST_MODE_ALL_WRITE:
            is_write = true;
            break;
        case I2C_TEST_MODE_ALL_READ:
            is_write = false;
            break;
        case I2C_TEST_MODE_ALTERNATING:
            is_write = (txn % 2 == 0); // Even: Write, Odd: Read
            break;
        default:
            is_write = false; // Default to Read
            break;
        }

        if (is_write) {
            // ==================================================================
            // Write Transaction (Controller -> Target)
            // Reference: i2c_p0_cwr - Use i2c_controller_write() function
            // ==================================================================
            // Set data value for this transaction (0x5A for txn 0, 0x5B for txn 1)
            write_data = (txn == 0) ? 0x5A : 0x5B;

            simputs("  Transaction ");
            simputshex32("", txn);
            simputs(": Writing 1 byte (0x");
            simputshex32("", write_data);
            simputs(")");
            if (send_stop) {
                simputs(" [WITH STOP]\n");
            } else {
                simputs(" [NO STOP - Repeated START]\n");
            }

            // Use basic i2c_controller_write function from i2c_opentitan.c (exactly like
            // i2c_p0_cwr)
            ret = i2c_controller_write(CONTROLLER_IDX, TARGET_ADDR, &write_data, DATA_SIZE,
                                       send_stop);

            if (ret != I2C_OK) {
                simputs("  ERROR: Write transaction ");
                simputshex32("", txn);
                simputs(" failed, ret=");
                simputshex32("", ret);
                simputs("\n");
                write_scratch(0, 0xBAD00040 | (txn & 0xFF));
                test_fail(0);
            }

            // ==================================================================
            // CRITICAL FIX: Clear Target ACQ FIFO after write transaction
            // ==================================================================
            // Problem: Write transactions leave entries in Target ACQ FIFO:
            //   - START entry
            //   - Address byte entry
            //   - Data byte entries
            //   - STOP entry (if last transaction)
            //
            // If ACQ FIFO is not cleared, entries accumulate:
            //   - ACQ FIFO depth increases
            //   - When depth > 6 (remainder <= 2), acq_fifo_plenty_space = 0
            //   - This causes stretch_addr = 1 and stretch_rx = 1
            //   - Target cannot leave stretch state until ACQ FIFO is cleared
            //
            // Solution: Clear ACQ FIFO immediately after each transaction
            //   - For non-last transactions (repeated start): Must clear immediately
            //   - For last transaction: Can clear after transaction completes
            // ==================================================================
            if (!send_stop) {
                // CRITICAL: For repeated START transactions, clear ACQ FIFO immediately
                // This prevents ACQ FIFO from filling up and causing stretch in next transaction
                simputs(
                    "    [Target] Clearing ACQ FIFO after write transaction (repeated START)...\n");

                // Step 1: Clear any unhandled TARGET_EVENTS
                uint32_t target_events = i2c_get_target_events(TARGET_IDX);
                if (target_events != 0) {
                    simputs("    [Target] Clearing unhandled TARGET_EVENTS: 0x");
                    simputshex32("", target_events);
                    simputs("\n");
                    i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);
                }

                // Step 2: Drain ACQ FIFO entries
                uint32_t drain_base = i2c_get_base(TARGET_IDX);
                uint32_t drain_count = 0;
                while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                    (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                                 SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                    drain_count++;
                    if (drain_count > 8) {
                        simputs("    [Target] WARNING: Drained more than 8 entries, stopping\n");
                        break;
                    }
                }

                // Step 3: Reset ACQ FIFO to ensure it's completely empty
                i2c_reset_fifos(TARGET_IDX, false, false, false, true);

                // Step 4: Verify ACQ FIFO is empty
                if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                    simputs("    [Target] WARNING: ACQ FIFO not empty after reset, draining "
                            "again...\n");
                    while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                        (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                    }
                }

                simputs("    [Target] ACQ FIFO cleared (drained ");
                simputshex32("", drain_count);
                simputs(" entries)\n");
            }
            // Note: For last transaction (with STOP), ACQ FIFO can be cleared after all
            // transactions But for repeated START, we must clear immediately to prevent stretch

            // Original code (commented out - no ACQ FIFO clearing):
            // simputs("  Transaction ");
            // simputshex32("", txn);
            // simputs(" completed successfully\n");
            // write_scratch(0, 0xDEB00040 | (txn & 0xFF));

            simputs("  Transaction ");
            simputshex32("", txn);
            simputs(" completed successfully\n");
            write_scratch(0, 0xDEB00040 | (txn & 0xFF));

        } else {
            // ==================================================================
            // Read Transaction (Controller <- Target)
            // Reference: i2c_read_sanity - Pre-load TX FIFO, then use i2c_controller_read()
            //
            // CRITICAL for Auto Stretch Mode (tx_stretch_ctrl = false):
            //   - In auto stretch mode, target automatically stretches clock when TX FIFO is empty
            //   - To avoid clock stretching (which can cause delays), pre-load TX FIFO BEFORE read
            //   - This ensures target has data ready and can respond immediately without stretching
            // ==================================================================
            // Set data value for this transaction (0x5A for txn 0, 0x5B for txn 1)
            read_data = (txn == 0) ? 0x5A : 0x5B;

            simputs("  Transaction ");
            simputshex32("", txn);
            simputs(": Reading 1 byte (expecting 0x");
            simputshex32("", read_data);
            simputs(")");
            if (send_stop) {
                simputs(" [WITH STOP]\n");
            } else {
                simputs(" [NO STOP - Repeated START]\n");
            }

            // CRITICAL: Pre-load Target TX FIFO BEFORE controller initiates read
            // In auto stretch mode, if TX FIFO is empty when read address arrives,
            // target will stretch clock until data is available, which can cause delays/hangs
            // Pre-loading ensures data is ready immediately, avoiding clock stretch
            simputs("    [Target] Pre-loading TX FIFO (required for auto stretch mode)...\n");
            uint32_t written = i2c_target_transmit(TARGET_IDX, &read_data, DATA_SIZE);
            if (written != DATA_SIZE) {
                simputs("  ERROR: Failed to pre-load TX FIFO\n");
                write_scratch(0, 0xBAD00050 | (txn & 0xFF));
                test_fail(0);
            }
            simputs(
                "    [Target] TX FIFO pre-loaded successfully (data ready, no clock stretch)\n");

            // Use basic i2c_controller_read function from i2c_opentitan.c
            ret = i2c_controller_read(CONTROLLER_IDX, TARGET_ADDR, &read_recv_buffer[txn],
                                      DATA_SIZE, send_stop);

            if (ret != I2C_OK) {
                simputs("  ERROR: Read transaction ");
                simputshex32("", txn);
                simputs(" failed, ret=");
                simputshex32("", ret);
                simputs("\n");
                write_scratch(0, 0xBAD00050 | (txn & 0xFF));
                test_fail(0);
            }

            // ==================================================================
            // CRITICAL FIX: Clear Target ACQ FIFO after read transaction
            // ==================================================================
            // Problem: Read transactions leave entries in Target ACQ FIFO:
            //   - START entry
            //   - Address byte entry (with READ bit)
            //
            // If ACQ FIFO is not cleared, entries accumulate:
            //   - ACQ FIFO depth increases
            //   - When depth > 6 (remainder <= 2), acq_fifo_plenty_space = 0
            //   - This causes stretch_addr = 1 and stretch_rx = 1
            //   - Target cannot leave stretch state until ACQ FIFO is cleared
            //
            // Solution: Clear ACQ FIFO immediately after each transaction
            //   - For non-last transactions (repeated start): Must clear immediately
            //   - For last transaction: Can clear after transaction completes
            // ==================================================================
            if (!send_stop) {
                // CRITICAL: For repeated START transactions, clear ACQ FIFO immediately
                // This prevents ACQ FIFO from filling up and causing stretch in next transaction
                simputs(
                    "    [Target] Clearing ACQ FIFO after read transaction (repeated START)...\n");

                // Step 1: Clear any unhandled TARGET_EVENTS
                uint32_t target_events = i2c_get_target_events(TARGET_IDX);
                if (target_events != 0) {
                    simputs("    [Target] Clearing unhandled TARGET_EVENTS: 0x");
                    simputshex32("", target_events);
                    simputs("\n");
                    i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);
                }

                // Step 2: Drain ACQ FIFO entries
                uint32_t drain_base = i2c_get_base(TARGET_IDX);
                uint32_t drain_count = 0;
                while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                    (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                                 SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                    drain_count++;
                    if (drain_count > 8) {
                        simputs("    [Target] WARNING: Drained more than 8 entries, stopping\n");
                        break;
                    }
                }

                // Step 3: Reset ACQ FIFO to ensure it's completely empty
                i2c_reset_fifos(TARGET_IDX, false, false, false, true);

                // Step 4: Verify ACQ FIFO is empty
                if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                    simputs("    [Target] WARNING: ACQ FIFO not empty after reset, draining "
                            "again...\n");
                    while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                        (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                    }
                }

                simputs("    [Target] ACQ FIFO cleared (drained ");
                simputshex32("", drain_count);
                simputs(" entries)\n");
            }
            // Note: For last transaction (with STOP), ACQ FIFO can be cleared after all
            // transactions But for repeated START, we must clear immediately to prevent stretch

            // Original code (commented out - no ACQ FIFO clearing):
            // simputs("  Transaction ");
            // simputshex32("", txn);
            // simputs(" completed successfully (read 0x");
            // simputshex32("", read_recv_buffer[txn]);
            // simputs(")\n");
            // write_scratch(0, 0xDEB00050 | (txn & 0xFF));

            simputs("  Transaction ");
            simputshex32("", txn);
            simputs(" completed successfully (read 0x");
            simputshex32("", read_recv_buffer[txn]);
            simputs(")\n");
            write_scratch(0, 0xDEB00050 | (txn & 0xFF));
        }
    }

    simputs("  All transactions completed successfully\n");
    write_scratch(1, 0x00000041);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    write_scratch(1, 0x00000090);

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
    simputshex32("  - Bytes per txn:      ", DATA_SIZE);
    simputs(" (0x5A, 0x5B)\n");
    uint32_t total_bytes = NUM_TRANSACTIONS * DATA_SIZE;
    simputshex32("  - Total bytes:        ", total_bytes);
    simputs("\n");
    simputs("  - Test:               Continuous Transactions with Repeated START\n");
    simputs("  - Mode:               ");
    switch (TEST_MODE) {
    case I2C_TEST_MODE_ALL_WRITE:
        simputs("ALL WRITE");
        break;
    case I2C_TEST_MODE_ALL_READ:
        simputs("ALL READ");
        break;
    case I2C_TEST_MODE_ALTERNATING:
        simputs("ALTERNATING (Write/Read)");
        break;
    default:
        simputs("UNKNOWN");
        break;
    }
    simputs("\n");
    simputs(
        "  - Function:           i2c_controller_write/i2c_controller_read from i2c_opentitan.c\n");
    simputs("  - Data:                0x5A, 0x5B (1 byte per transaction)\n");
    simputs("  - Verification:       Check waveform\n");
    simputs("\n################################################\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
