/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_read_sanity.c
 * @brief I2C Read Sanity Test - controller reads pre-loaded target TX data
 *
 * Checks that I2C_1 as controller reads back exactly the bytes that I2C_0 as
 * target has queued for transmission, over two reads with distinct data.
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
 * @brief Connect an I2C instance to the pads in controller or target mode.
 *
 * Must run before the I2C IP of that instance is configured.
 *
 * @param idx I2C instance (0 or 1)
 * @param controller_mode true for Controller mode, false for Target mode
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

//=============================================================================
// Main Test
//=============================================================================

int main(void) {
    const uint32_t TARGET_IDX = 0;
    const uint32_t CONTROLLER_IDX = 1;
    const uint8_t TARGET_ADDR = 0x10; // 7-bit
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##    I2C Read Sanity Test - Concise Version  ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");

    simputs("  System ready\n");

    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");

    i2c_wrapper_enable(TARGET_IDX, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    simputs("  Initializing I2C_0 Target (addr=0x10)...\n");

    // Derive the bus timing from the physical bus characteristics
    i2c_timing_physical_t physical_params = {
        .speed = I2C_SPEED_STANDARD, // 100 kHz
        .clock_period_nanos = 5,     // 200 MHz peripheral clock
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
                                   .timing = computed_timing,
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

    // Record START and STOP conditions in the target acquisition FIFO
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    simputs("  Initializing I2C_1 Controller...\n");

    // Controller uses the same timing as the target
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
    simputs("\nStep 4: Multiple I2C Read Communication Tests\n");

    const uint32_t NUM_TRANSACTIONS = 2;

    unsigned char test_data_base[] = {0xAC, 0x8F, 0x73, 0xB2};
    uint32_t data_size = sizeof(test_data_base);

    unsigned char test_data[NUM_TRANSACTIONS][4];   // Expected data (what Target sends)
    unsigned char recv_buffer[NUM_TRANSACTIONS][4]; // Received data (what Controller reads)

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        for (uint32_t i = 0; i < data_size; i++) {
            // Make each transaction's pattern unique
            test_data[txn][i] = test_data_base[i] ^ (txn & 0xFF);
        }
    }

    write_scratch(1, 0x00000041);

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
        // A target with more than one acquisition FIFO entry, or with unhandled
        // target events, stretches the clock on a read; start each read from an
        // empty FIFO and no pending events.
        i2c_reset_fifos(TARGET_IDX, false, false, false, true);

        uint32_t target_events = i2c_get_target_events(TARGET_IDX);
        if (target_events != 0) {
            i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);
        }

        // Drain anything the FIFO reset left behind
        if (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
            uint32_t drain_base = i2c_get_base(TARGET_IDX);
            while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
                (void)read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            }
        }

        // Queue the response before the read request arrives
        uint32_t bytes_sent = i2c_target_transmit(TARGET_IDX, test_data[txn], data_size);
        if (bytes_sent != data_size) {
            simputs("  ERROR: Failed to pre-load TX FIFO at txn ");
            simputshex32("", txn);
            simputs("\n");
            write_scratch(0, 0xBAD00040 | (txn & 0xFF));
            test_fail(0);
        }

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

        // A read leaves its START and address entries in the acquisition FIFO;
        // drain them so they cannot stretch the next read
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

    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Data Verification for All Transactions\n");

    uint32_t total_errors = 0;

    for (uint32_t txn = 0; txn < NUM_TRANSACTIONS; txn++) {
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
    simputshex32("  - Bytes per txn:      ", data_size);
    simputs("\n");
    uint32_t total_bytes = NUM_TRANSACTIONS * data_size;
    simputshex32("  - Total bytes:        ", total_bytes);
    simputs("\n");
    simputs("  - Verification:       PASS\n");
    simputs("\n################################################\n");

    test_pass(0);
}
