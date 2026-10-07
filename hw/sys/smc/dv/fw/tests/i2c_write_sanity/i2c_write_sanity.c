/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_write_sanity.c
 * @brief I2C controller-to-target write test between two on-chip instances
 *
 * Verifies that writes from I2C_1 as controller arrive intact at I2C_0 as
 * target, over five 4-byte transactions with distinct data.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

/* Iteration budget for each ACQ FIFO drain loop: above the FIFO depth, but
 * finite. Each loop needs its own budget, or the post-reset retry runs no
 * iterations once the first drain has spent it. */
#define ACQ_DRAIN_LOOP_LIMIT 100u

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
 * @brief Check and clear Target ACQ FIFO if not empty
 * @param target_idx Target I2C instance index
 * @return Number of entries drained (0 if already empty)
 */
static uint32_t i2c_target_check_and_clear_acq_fifo(uint32_t target_idx) {
    uint32_t acq_level = 0;
    uint32_t drained_count = 0;

    i2c_target_get_fifo_status(target_idx, NULL, &acq_level);

    if (acq_level == 0 && i2c_target_acq_fifo_empty(target_idx)) {
        return 0;
    }

    simputs("  [ACQ FIFO] ACQ FIFO not empty (level=");
    simputshex32("", acq_level);
    simputs("), draining...\n");

    uint32_t drain_base = i2c_get_base(target_idx);
    uint32_t drain_timeout = ACQ_DRAIN_LOOP_LIMIT;

    while (drain_timeout > 0 && !i2c_target_acq_fifo_empty(target_idx)) {
        (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        drained_count++;
        drain_timeout--;

        // Safety check: ACQ FIFO depth is 64, should never drain more
        if (drained_count > 64) {
            simputs("  [ACQ FIFO] WARNING: Drained more than 64 entries, stopping\n");
            break;
        }
    }

    if (drained_count > 0) {
        simputs("  [ACQ FIFO] Drained ");
        simputshex32("", drained_count);
        simputs(" entries\n");
    }

    if (!i2c_target_acq_fifo_empty(target_idx)) {
        simputs("  [ACQ FIFO] WARNING: ACQ FIFO still not empty after draining, resetting...\n");
        i2c_reset_fifos(target_idx, false, false, false, true);

        // Drain again after the reset, with its own budget.
        uint32_t retry_timeout = ACQ_DRAIN_LOOP_LIMIT;
        if (!i2c_target_acq_fifo_empty(target_idx)) {
            while (!i2c_target_acq_fifo_empty(target_idx) && retry_timeout > 0) {
                (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                retry_timeout--;
            }
        }
    }

    /* Stop if the FIFO is still not empty after the drain and the reset: a
     * stale ACQ FIFO can stall the write or leave stale data for the check. */
    if (!i2c_target_acq_fifo_empty(target_idx)) {
        simputs("  [ACQ FIFO] ERROR: ACQ FIFO not empty after drain and reset\n");
        write_scratch(0, 0xBAD00044);
        test_fail(0);
    }

    return drained_count;
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
    simputs("##   I2C P0 Write Test - Internal I2C          ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");
    simputs("  Enabling I2C_1 Controller (Master mode)...\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    simputs("  Enabling I2C_0 Target (Slave mode)...\n");
    i2c_wrapper_enable(TARGET_IDX, false);

    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    // Configure Controller timing. The I2C input clock for this image is 100 MHz.
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

    simputs("  Initializing I2C_0 Target...\n");
    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F, // Exact match
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
            false, // Automatic TX Stretch mode (hardware auto-manages, no SW intervention needed)
        .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00032);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");

    write_scratch(1, 0x00000031);

    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
    simputs("  Speed: Standard mode (100 kHz)\n");
    simputs("  Address mode: 7-bit addressing\n");

    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Write Preset Data from Controller to Target\n");

    const uint32_t NUM_TRANSACTIONS = 5;

    // Test data patterns
    unsigned char test_data_base[] = {0xAC, 0x8F, 0x73, 0xB2};
    uint32_t data_size = sizeof(test_data_base);

    unsigned char test_data[NUM_TRANSACTIONS][4];     // Data to send (Controller -> Target)
    unsigned char recv_buffer[NUM_TRANSACTIONS][256]; // Received data (Target receives)
    uint32_t received_lens[NUM_TRANSACTIONS];

    // Prepare test data with unique patterns for each transaction
    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        for (uint32_t i = 0; i < data_size; i++) {
            test_data[txn][i] = test_data_base[i] ^ (txn & 0xFF);
        }
    }

    simputs("  Target address: 0x");
    simputshex32("", TARGET_ADDR);
    simputs("\n");

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        simputs("  Transaction ");
        simputshex32("", txn);
        simputs(": Writing ");
        simputshex32("", data_size);
        simputs(" bytes\n");
        simputs("  Data to write: 0x");
        for (uint32_t i = 0; i < data_size; i++) {
            simputshex32("", test_data[txn][i]);
            if (i < data_size - 1) simputs(" ");
        }
        simputs("\n");

        // A non-empty target ACQ FIFO can stretch SCL and deadlock the write.
        uint32_t drained_count = i2c_target_check_and_clear_acq_fifo(TARGET_IDX);
        if (drained_count > 0) {
            simputs("  [PRE-WRITE] ACQ FIFO cleared before write transaction\n");
        }

        // Non-blocking write: the target must receive while the controller sends,
        // or the ACQ FIFO overflows and stretches SCL.
        simputs("  Controller sending write transaction (non-blocking)...\n");
        ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, test_data[txn],
                                                        data_size);
        if (ret != I2C_OK) {
            simputs("  ERROR: Controller write failed with error code ");
            simputshex32("", ret);
            simputs("\n");
            write_scratch(0, 0xBAD00040);
            test_fail(0);
        }

        simputs("  Write command sent to FIFO\n");

        // Receive without waiting for the controller to go idle.
        simputs("  Target receiving transaction (immediate read)...\n");
        ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer[txn], sizeof(recv_buffer[txn]),
                                             &received_lens[txn], I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) {
            simputs("  ERROR: Target receive failed\n");
            write_scratch(0, 0xBAD00042);
            test_fail(0);
        }

        ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) {
            simputs("  ERROR: Wait for controller idle failed with error code ");
            simputshex32("", ret);
            simputs("\n");
            write_scratch(0, 0xBAD00041);
            test_fail(0);
        }

        simputshex32("  Target received ", received_lens[txn]);
        simputs(" bytes\n");
    }

    write_scratch(1, 0x00000041); // Signal to TB: Write complete

    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Compare Written and Received Data\n");
    simputs("  ========================================\n");
    simputs("  [VERIFY] Final Data Comparison:\n");
    simputs("  ========================================\n");

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        simputs("  Transaction ");
        simputshex32("", txn);
        simputs(":\n");
        simputs("    [VERIFY] Verifying received data:\n");
        simputs("    Expected length: ");
        simputshex32("", data_size);
        simputs(" bytes\n");
        simputshex32("    Received length: ", received_lens[txn]);
        simputs(" bytes\n");

        if (received_lens[txn] != data_size) {
            simputs("  ERROR: Target received incorrect length!\n");
            simputs("    Expected: ");
            simputshex32("", data_size);
            simputs(", Got: ");
            simputshex32("", received_lens[txn]);
            simputs("\n");
            write_scratch(0, 0xBAD00043);
            test_fail(0);
        }

        for (uint32_t i = 0; i < data_size; i++) {
            simputs("    Expected data byte[");
            simputshex32("", i);
            simputs("]: 0x");
            simputshex32("", test_data[txn][i]);
            simputs("\n");
            simputs("    Received data byte[");
            simputshex32("", i);
            simputs("]: 0x");
            simputshex32("", recv_buffer[txn][i]);
            simputs("\n");

            if (recv_buffer[txn][i] != test_data[txn][i]) {
                simputs("  ERROR: Target received incorrect data!\n");
                simputs("    Expected: 0x");
                for (uint32_t j = 0; j < data_size; j++) {
                    simputshex32("", test_data[txn][j]);
                    if (j < data_size - 1) simputs(" ");
                }
                simputs("\n");
                simputs("    Got:      0x");
                for (uint32_t j = 0; j < data_size; j++) {
                    simputshex32("", recv_buffer[txn][j]);
                    if (j < data_size - 1) simputs(" ");
                }
                simputs("\n");
                write_scratch(0, 0xBAD00043);
                test_fail(0);
            }
        }

        simputs("  [VERIFY] Write verification PASSED!\n");
        simputs("    Written data: 0x");
        for (uint32_t i = 0; i < data_size; i++) {
            simputshex32("", test_data[txn][i]);
            if (i < data_size - 1) simputs(" ");
        }
        simputs(" (correct)\n");
        simputs("  Write transaction completed successfully\n");
    }

    simputs("  [SUCCESS] All transactions verified successfully!\n");
    simputs("  ========================================\n");
    write_scratch(1, 0x00000051);

    write_scratch(1, 0x00000090);

    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    simputs("Summary:\n");
    simputs("  - I2C_1 (Controller): @ 0xC0009200\n");
    simputs("  - I2C_0 (Target):    @ 0xC0009000, Addr 0x");
    simputshex32("", TARGET_ADDR);
    simputs("\n");
    simputshex32("  - Total transactions: ", NUM_TRANSACTIONS);
    simputs("\n");
    simputshex32("  - Bytes per transaction: ", data_size);
    simputs("\n");
    uint32_t total_bytes = NUM_TRANSACTIONS * data_size;
    simputshex32("  - Total bytes:        ", total_bytes);
    simputs("\n");
    simputs("  - Verification:       PASS\n");
    simputs("\n################################################\n");

    test_pass(0);
}
