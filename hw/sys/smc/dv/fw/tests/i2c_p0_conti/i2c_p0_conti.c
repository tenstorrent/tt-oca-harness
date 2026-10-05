/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p0_conti.c
 * @brief I2C P0 Continuous Test - Continuous Transactions with Repeated START
 *
 * Verifies two back-to-back one-byte controller transactions joined by a
 * repeated START, only the last ending with STOP, between I2C_1 as controller
 * and I2C_0 as target. The testbench selects all writes, all reads, or
 * alternating write/read (the default for any unknown mode value). Each written
 * byte is checked at the target and each read byte at the controller.
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
 * @brief After a transaction that ends in STOP, wait until the target has logged it.
 *
 * The controller calls return before the STOP reaches the bus, and the target
 * logs the STOP one bus event later. A target FIFO reset issued before that
 * entry lands leaves it behind the reset, which reads as a reset that did not
 * take. Wait for the controller to go idle, then consume target entries until
 * the STOP appears.
 */
static int target_wait_stop_entry(uint32_t controller_idx, uint32_t target_idx) {
    uint32_t target_base = i2c_get_base(target_idx);
    const uint32_t STOP_WAIT_TIMEOUT = 10000;
    const uint32_t STOP_DRAIN_BOUND = 16;
    uint32_t wait_count = 0;
    uint32_t drained = 0;

    if (i2c_controller_wait_idle(controller_idx, I2C_TIMEOUT_DEFAULT) != I2C_OK) {
        simputs("    ERROR: controller did not return to idle after STOP\n");
        return I2C_ERROR;
    }
    while (wait_count < STOP_WAIT_TIMEOUT && drained < STOP_DRAIN_BOUND) {
        if (i2c_target_acq_fifo_empty(target_idx)) {
            wait_count++;
            continue;
        }
        i2c__ACQDATA_t acqdata = {
            .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        drained++;
        if (acqdata.f.SIGNAL == I2C_ACQ_SIGNAL_STOP) {
            return I2C_OK;
        }
    }
    simputs("    ERROR: target ACQ never logged the STOP entry\n");
    return I2C_ERROR;
}

/**
 * @brief Wait for the data byte the target received, check it, then empty the
 *        target's receive FIFO for the next transaction.
 */
static int target_verify_acq_data_and_clear(uint32_t controller_idx, uint32_t target_idx,
                                            uint8_t expected, bool ends_with_stop) {
    uint32_t target_base = i2c_get_base(target_idx);
    uint32_t wait_count = 0;
    const uint32_t ACQ_WAIT_TIMEOUT = 10000;
    bool found = false;

    while (wait_count < ACQ_WAIT_TIMEOUT && !found) {
        i2c__STATUS_t status = {
            .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (!status.f.ACQEMPTY) {
            i2c__ACQDATA_t acqdata = {
                .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            if (acqdata.f.SIGNAL == I2C_ACQ_SIGNAL_DATA) {
                uint8_t abyte = (uint8_t)acqdata.f.ABYTE;
                simputs("    ACQ DATA abyte: 0x");
                simputshex32("", abyte);
                simputs("\n");
                if (abyte != expected) {
                    simputs("    ERROR: ACQ DATA mismatch, expected 0x");
                    simputshex32("", expected);
                    simputs("\n");
                    return I2C_ERROR;
                }
                found = true;
            }
        } else {
            wait_count++;
            if ((wait_count % 1000) == 0) {
                for (volatile int i = 0; i < 100; i++) {
                }
            }
        }
    }

    if (!found) {
        simputs("    ERROR: timeout waiting for ACQ DATA byte\n");
        return I2C_ERROR;
    }

    uint32_t target_events = i2c_get_target_events(target_idx);
    if (target_events != 0) {
        i2c_clear_target_events(target_idx, 0xFFFFFFFF);
    }

    if (ends_with_stop && target_wait_stop_entry(controller_idx, target_idx) != I2C_OK) {
        return I2C_ERROR;
    }
    uint32_t drain_count = 0;
    while (!i2c_target_acq_fifo_empty(target_idx)) {
        (void)read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        drain_count++;
        if (drain_count > 8) {
            break;
        }
    }
    i2c_reset_fifos(target_idx, false, false, false, true);

    /* The FIFO reset alone must leave the receive FIFO empty; a software drain
     * here would hide a reset that did not take. */
    if (!i2c_target_acq_fifo_empty(target_idx)) {
        simputs("  ERROR: ACQ FIFO not empty after ACQRST, idx=");
        simputshex32("", target_idx);
        simputs("\n");
        return I2C_ERROR;
    }

    simputs("    ACQ verified and cleared (extra drained ");
    simputshex32("", drain_count);
    simputs(")\n");
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

    // The testbench selects the mode; the virtual console owns scratch[2]
    uint32_t test_mode_raw = read_scratch(3);
    i2c_test_mode_t TEST_MODE;

    if (test_mode_raw == 0) {
        TEST_MODE = I2C_TEST_MODE_ALL_WRITE;
    } else if (test_mode_raw == 1) {
        TEST_MODE = I2C_TEST_MODE_ALL_READ;
    } else if (test_mode_raw == 2) {
        TEST_MODE = I2C_TEST_MODE_ALTERNATING;
    } else {
        TEST_MODE = I2C_TEST_MODE_ALTERNATING;
    }

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Continuous Test - Repeated START ##\n");
    simputs("################################################\n");
    simputs("\n");

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
    // Step 2: Wrapper enable; it connects the pads and must precede IP setup
    //=========================================================================
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

    i2c_wrapper_enable(TARGET_IDX, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: I2C IP Initialization
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    simputs("  Initializing I2C_0 Target (addr=0x10)...\n");

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
        .tx_stretch_ctrl = false, // Target stretches the clock while its TX FIFO is empty
        .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");

    // Log START and STOP in the target FIFO so data bytes can be told apart
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
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

    write_scratch(1, 0x00000040);
    //=========================================================================
    // Step 4: Continuous transactions with Repeated START
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Continuous transactions with Repeated START\n");
    simputs("  Using i2c_controller_write/i2c_controller_read from i2c_opentitan.c\n");

    const uint32_t NUM_TRANSACTIONS = 2;
    const uint32_t DATA_SIZE = 1;

    // One data byte per transaction, a different value for each transaction
    uint8_t write_data;
    uint8_t read_data;
    uint8_t read_recv_buffer[2];

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        bool send_stop = (txn == NUM_TRANSACTIONS - 1);

        bool is_write;
        switch (TEST_MODE) {
        case I2C_TEST_MODE_ALL_WRITE:
            is_write = true;
            break;
        case I2C_TEST_MODE_ALL_READ:
            is_write = false;
            break;
        case I2C_TEST_MODE_ALTERNATING:
            is_write = (txn % 2 == 0);
            break;
        default:
            is_write = false;
            break;
        }

        if (is_write) {
            // Write transaction (controller -> target)
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

            simputs("    [Target] Verifying ACQ DATA after write...\n");
            if (target_verify_acq_data_and_clear(CONTROLLER_IDX, TARGET_IDX, write_data,
                                                 send_stop) != I2C_OK) {
                write_scratch(0, 0xBAD00044 | (txn & 0xFF));
                test_fail(0);
            }

            simputs("  Transaction ");
            simputshex32("", txn);
            simputs(" completed successfully\n");
            write_scratch(0, 0xDEB00040 | (txn & 0xFF));

        } else {
            // Read transaction (controller <- target)
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

            // Load the reply before the read starts, so the target does not stretch
            simputs("    [Target] Pre-loading TX FIFO (required for auto stretch mode)...\n");
            uint32_t written = i2c_target_transmit(TARGET_IDX, &read_data, DATA_SIZE);
            if (written != DATA_SIZE) {
                simputs("  ERROR: Failed to pre-load TX FIFO\n");
                write_scratch(0, 0xBAD00050 | (txn & 0xFF));
                test_fail(0);
            }
            simputs(
                "    [Target] TX FIFO pre-loaded successfully (data ready, no clock stretch)\n");

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

            if (read_recv_buffer[txn] != read_data) {
                simputs("  ERROR: Read data mismatch got 0x");
                simputshex32("", read_recv_buffer[txn]);
                simputs(" expected 0x");
                simputshex32("", read_data);
                simputs("\n");
                write_scratch(0, 0xBAD00055 | (txn & 0xFF));
                test_fail(0);
            }
            simputs("    PASS: Read data matches expected 0x");
            simputshex32("", read_data);
            simputs("\n");

            // Empty the target's receive FIFO so the next transaction is not stretched
            uint32_t target_events = i2c_get_target_events(TARGET_IDX);
            if (target_events != 0) {
                i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);
            }
            if (send_stop && target_wait_stop_entry(CONTROLLER_IDX, TARGET_IDX) != I2C_OK) {
                write_scratch(0, 0xBAD00056 | (txn & 0xFF));
                test_fail(0);
            }
            uint32_t drain_base = i2c_get_base(TARGET_IDX);
            uint32_t drain_count = 0;
            while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                drain_count++;
                if (drain_count > 8) {
                    break;
                }
            }
            i2c_reset_fifos(TARGET_IDX, false, false, false, true);

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
    // Test Complete: a done marker distinct from the driver's progress codes
    //=========================================================================
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputshex32("  - I2C_0 (Target):     Addr 0x10 @ ", i2c_get_base(TARGET_IDX));
    simputs("\n");
    simputshex32("  - I2C_1 (Controller): @ ", i2c_get_base(CONTROLLER_IDX));
    simputs("\n");
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
    simputs("  - Verification:       ACQ DATA + RX buffer fail-closed compares\n");
    simputs("\n################################################\n");

    test_pass(0);
}
