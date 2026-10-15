/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p0_rdwr.c
 * @brief I2C P0 Read-Write Test - Internal I2C Communication
 *
 * Verifies a write and a register-style read between two internal instances,
 * I2C_0 as controller and I2C_1 as target, at standard speed with 7-bit
 * addressing. The target has no register model: firmware loads the read reply
 * into the target, so the read checks the transfer, not that the written data
 * was stored. Before the read, the test checks that the target is idle with
 * its reply loaded, no events pending and its receive FIFO empty.
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
    const uint32_t CONTROLLER_IDX = 0; // I2C_0 as Controller
    const uint32_t TARGET_IDX = 1;     // I2C_1 as Target
    const uint8_t TARGET_ADDR = 0x10;  // Target address (7-bit)
    const uint8_t REG_ADDR = 0x5A;     // Register address for write/read
    const uint16_t TEST_DATA = 0x5A5A; // Known data pattern to write (2 bytes)
    uint16_t read_value = 0;           // Data read back from register
    int ret;

    /* Poll bound for the write leg's waits. It covers the healthy transfer with
     * about 4x margin and expires well inside the testbench's completion wait,
     * so a failure prints its own diagnostics instead of ending in a testbench
     * timeout. I2C_TIMEOUT_DEFAULT is sized for clock-stretching tests and
     * expires too late for that. */
    const uint32_t I2C_RDWR_WAIT_BOUND = 4000;

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Read-Write Test - Internal I2C    ##\n");
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
    // Step 2: Wrapper enable for both the controller and the target
    //=========================================================================
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");
    simputs("  Enabling I2C_0 Controller (Master mode)...\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    simputs("  Enabling I2C_1 Target (Slave mode)...\n");
    i2c_wrapper_enable(TARGET_IDX, false);

    write_scratch(1, 0x00000021);

    //=========================================================================
    // Step 3: I2C IP Initialization
    //=========================================================================
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");

    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        /* Every transfer depends on the computed timing, so there is no
         * fallback. */
        simputs("  ERROR: Physical timing computation failed, error code ");
        simputshex32("", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    simputs("  Initializing I2C_0 Controller...\n");
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

    simputs("  Initializing I2C_1 Target...\n");
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
        write_scratch(0, 0xBAD00032);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");

    write_scratch(1, 0x00000031);

    // Log START and STOP in the target's receive FIFO
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
    simputs("  Speed: Standard mode (100 kHz)\n");
    simputs("  Address mode: 7-bit addressing\n");

    //=========================================================================
    // Step 4: Write preset data from Controller to Target
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("\nStep 4: Write Preset Data from Controller to Target\n");
    simputs("  Register address: 0x");
    simputshex32("", REG_ADDR);
    simputs("\n");
    simputs("  Data to write: 0x");
    simputshex32("", TEST_DATA);
    simputs("\n");
    simputs("  Target address: 0x");
    simputshex32("", TARGET_ADDR);
    simputs("\n");

    // Register address, then the data low byte and high byte
    uint8_t write_buffer[3];
    write_buffer[0] = REG_ADDR;
    write_buffer[1] = TEST_DATA & 0xFF;
    write_buffer[2] = (TEST_DATA >> 8) & 0xFF;

    // Queue the write without waiting, so the target can receive it as it arrives
    simputs("  Controller sending write transaction (non-blocking)...\n");
    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, write_buffer, 3);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller write failed with error code ");
        simputshex32("", ret);
        simputs("\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    simputs("  Write command sent to FIFO\n");

    // Receive on the target before waiting for the controller to finish
    simputs("  Target receiving transaction (immediate read)...\n");
    uint8_t recv_buffer[256];
    uint32_t received_len = 0;
    ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer, sizeof(recv_buffer),
                                         &received_len, I2C_RDWR_WAIT_BOUND);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive failed with error code ");
        simputshex32("", (uint32_t)ret);
        simputs("\n");
        simputshex32("    Bytes received before failure: ", received_len);
        simputs("\n");
        simputshex32("    Target STATUS: ", i2c_get_status(TARGET_IDX));
        simputs("\n");
        simputshex32("    Target TARGET_EVENTS: ", i2c_get_target_events(TARGET_IDX));
        simputs("\n");
        simputshex32("    Controller STATUS: ", i2c_get_status(CONTROLLER_IDX));
        simputs("\n");
        simputshex32("    Controller CONTROLLER_EVENTS: ",
                     i2c_get_controller_events(CONTROLLER_IDX));
        simputs("\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }

    // Wait for controller to become idle after target receive completes
    ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_RDWR_WAIT_BOUND);
    if (ret != I2C_OK) {
        simputs("  ERROR: Wait for controller idle failed with error code ");
        simputshex32("", (uint32_t)ret);
        simputs("\n");
        /* After an unexpected NACK the controller never reports idle; its
         * events tell that apart from a stalled bus. */
        simputshex32("    Controller STATUS: ", i2c_get_status(CONTROLLER_IDX));
        simputs("\n");
        simputshex32("    Controller CONTROLLER_EVENTS: ",
                     i2c_get_controller_events(CONTROLLER_IDX));
        simputs("\n");
        simputshex32("    Target STATUS: ", i2c_get_status(TARGET_IDX));
        simputs("\n");
        simputshex32("    Target TARGET_EVENTS: ", i2c_get_target_events(TARGET_IDX));
        simputs("\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }

    simputshex32("  Target received ", received_len);
    simputs(" bytes\n");

    simputs("  [VERIFY] Verifying received data:\n");
    simputs("    Expected length: 3 bytes\n");
    simputshex32("    Received length: ", received_len);
    simputs(" bytes\n");
    simputs("    Expected register address: 0x");
    simputshex32("", REG_ADDR);
    simputs("\n");
    simputs("    Received register address: 0x");
    simputshex32("", recv_buffer[0]);
    simputs("\n");
    simputs("    Expected data low byte: 0x");
    simputshex32("", TEST_DATA & 0xFF);
    simputs("\n");
    simputs("    Received data low byte: 0x");
    simputshex32("", recv_buffer[1]);
    simputs("\n");
    simputs("    Expected data high byte: 0x");
    simputshex32("", (TEST_DATA >> 8) & 0xFF);
    simputs("\n");
    simputs("    Received data high byte: 0x");
    simputshex32("", recv_buffer[2]);
    simputs("\n");

    if (received_len != 3) {
        simputs("  ERROR: Target received incorrect length!\n");
        simputshex32("    Expected: 3, Got: ", received_len);
        simputs("\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }

    if (recv_buffer[0] != REG_ADDR) {
        simputs("  ERROR: Target received incorrect register address!\n");
        simputs("    Expected: 0x");
        simputshex32("", REG_ADDR);
        simputs(", Got: 0x");
        simputshex32("", recv_buffer[0]);
        simputs("\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }

    uint16_t received_data = recv_buffer[1] | (recv_buffer[2] << 8);
    if (received_data != TEST_DATA) {
        simputs("  ERROR: Target received incorrect data!\n");
        simputs("    Expected: 0x");
        simputshex32("", TEST_DATA);
        simputs(", Got: 0x");
        simputshex32("", received_data);
        simputs("\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }

    simputs("  [VERIFY] Write verification PASSED!\n");
    simputs("    Register address: 0x");
    simputshex32("", REG_ADDR);
    simputs(" (correct)\n");
    simputs("    Written data: 0x");
    simputshex32("", TEST_DATA);
    simputs(" (correct)\n");
    simputs("  Write transaction completed successfully\n");
    write_scratch(1, 0x00000041);

    //=========================================================================
    // Step 5: Prepare Target for read operation
    //=========================================================================
    write_scratch(1, 0x00000050);
    simputs("\nStep 5: Prepare Target for Read Operation\n");

    /* The target stretches a read while its TX FIFO is empty, while it has
     * unhandled events, or while its receive FIFO holds more than one entry.
     * Load the reply first, then clear the events and reset the receive FIFO,
     * in that order, and wait for the target to go idle. */
    simputs(
        "  Preparing Target for read transaction (correct sequence to clear stretch events)...\n");

    simputshex32("", TEST_DATA);
    simputs("\n");

    uint8_t tx_data[2];
    tx_data[0] = TEST_DATA & 0xFF;
    tx_data[1] = (TEST_DATA >> 8) & 0xFF;

    uint32_t tx_bytes = i2c_target_transmit(TARGET_IDX, tx_data, 2);
    if (tx_bytes != 2) {
        simputs("  ERROR: Failed to pre-load Target TX FIFO\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }

    simputs("  Target TX FIFO pre-loaded with 2 bytes\n");

    // Loading the TX FIFO can raise target events; clear them
    uint32_t target_events = i2c_get_target_events(TARGET_IDX);
    if (target_events != 0) {
        simputshex32("  Clearing unhandled TARGET_EVENTS: ", target_events);
        simputs("\n");
        i2c_clear_target_events(TARGET_IDX, 0xFFFFFFFF);
    }
    /* The clear can leave events set; the log reports TARGET_EVENTS as read back. */
    target_events = i2c_get_target_events(TARGET_IDX);
    simputshex32("  TARGET_EVENTS after clear (sampled): ", target_events);
    simputs("\n");

    i2c_reset_fifos(TARGET_IDX, false, false, false, true); // Receive FIFO only
    simputs("  ACQ FIFO reset using ACQRST\n");

    /* The hardware reset alone must empty the receive FIFO. The print records
     * that the reset helper did not drain it in software; a FIFO still
     * occupied fails the test rather than being drained here. */
    simputshex32("  ACQRST needed software repair (0 = hardware reset took): ",
                 g_i2c_acq_reset_needed_drain);
    simputs("\n");
    {
        uint32_t acq_level_after_reset = 0;
        i2c_target_get_fifo_status(TARGET_IDX, NULL, &acq_level_after_reset);
        simputshex32("  ACQ level after ACQRST (sampled): ", acq_level_after_reset);
        simputs("\n");
        if (acq_level_after_reset != 0 || !i2c_target_acq_fifo_empty(TARGET_IDX)) {
            simputs("  ERROR: ACQ FIFO not empty after ACQRST\n");
            simputshex32("    ACQLVL: ", acq_level_after_reset);
            simputs("\n");
            write_scratch(0, 0xBAD00051);
            test_fail(0);
        }
    }
    simputs("  ACQ FIFO confirmed empty\n");

    write_scratch(1, 0x00000051);

    // The target must be idle, with SCL released, before the read request
    uint32_t target_base = i2c_get_base(TARGET_IDX);
    uint32_t idle_wait_count = 0;
    const uint32_t IDLE_WAIT_TIMEOUT = 10000;
    while (idle_wait_count < IDLE_WAIT_TIMEOUT) {
        i2c__STATUS_t status = {
            .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (status.f.TARGETIDLE) {
            for (volatile int i = 0; i < 500; i++)
                ;
            break;
        }
        idle_wait_count++;
        if (idle_wait_count % 1000 == 0) {
            for (volatile int i = 0; i < 100; i++)
                ;
        }
    }
    if (idle_wait_count >= IDLE_WAIT_TIMEOUT) {
        simputs("  ERROR: Target did not become idle before read request\n");
        write_scratch(0, 0xBAD00060);
        test_fail(0);
    } else {
        simputs("  Target confirmed idle (SCL should be released)\n");
    }

    /* Sample and check each read precondition just before the read. */
    target_events = i2c_get_target_events(TARGET_IDX);
    uint32_t acq_level_pre_read = 0;
    i2c_target_get_fifo_status(TARGET_IDX, NULL, &acq_level_pre_read);
    i2c__STATUS_t pre_read_status = {
        .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    simputshex32("  Pre-read TARGET_EVENTS (sampled): ", target_events);
    simputs("\n");
    simputshex32("  Pre-read ACQ level (sampled): ", acq_level_pre_read);
    simputs("\n");
    simputshex32("  Pre-read STATUS.TARGETIDLE (sampled): ", pre_read_status.f.TARGETIDLE);
    simputs("\n");
    if (target_events != 0) {
        simputs("  ERROR: TARGET_EVENTS not zero before read request\n");
        simputshex32("    TARGET_EVENTS: ", target_events);
        simputs("\n");
        write_scratch(0, 0xBAD00053);
        test_fail(0);
    }
    if (acq_level_pre_read != 0) {
        simputs("  ERROR: ACQ FIFO not empty before read request\n");
        simputshex32("    ACQLVL: ", acq_level_pre_read);
        simputs("\n");
        write_scratch(0, 0xBAD00054);
        test_fail(0);
    }
    if (!pre_read_status.f.TARGETIDLE) {
        simputs("  ERROR: Target not idle before read request\n");
        write_scratch(0, 0xBAD00055);
        test_fail(0);
    }

    //=========================================================================
    // Step 6: Read data from Target to Controller
    //=========================================================================
    write_scratch(1, 0x00000060);
    simputs("\nStep 6: Read Data from Target to Controller\n");
    simputs("  Reading from register address: 0x");
    simputshex32("", REG_ADDR);
    simputs("\n");

    /* Separate write and read calls let the target consume the register
     * address between the two phases. */
    uint8_t reg_addr_byte = REG_ADDR;
    uint8_t read_buffer[2];

    // Register address without STOP; the read follows with a repeated START
    ret = i2c_controller_write(CONTROLLER_IDX, TARGET_ADDR, &reg_addr_byte, 1, false);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller write (register address) failed\n");
        write_scratch(0, 0xBAD00061);
        test_fail(0);
    }

    simputs("  Processing register address from Target ACQ FIFO...\n");
    uint32_t acq_wait_count = 0;
    const uint32_t ACQ_WAIT_TIMEOUT = 10000;
    bool found_reg_addr = false;

    /* Two bounds: acq_wait_count limits polls of an empty FIFO, and
     * acq_entries_read limits entries consumed without finding the register
     * address. Reading more than a full FIFO of entries means the scan is not
     * converging. */
    uint32_t acq_entries_read = 0;
    const uint32_t ACQ_ENTRY_SCAN_LIMIT = I2C_TARGET_RX_FIFO_DEPTH;

    // Skip non-data entries; the first data entry must be the register address
    while (acq_wait_count < ACQ_WAIT_TIMEOUT && acq_entries_read < ACQ_ENTRY_SCAN_LIMIT &&
           !found_reg_addr) {
        i2c__STATUS_t status = {
            .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (!status.f.ACQEMPTY) {
            i2c__ACQDATA_t acqdata = {
                .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            uint32_t signal = acqdata.f.SIGNAL;
            uint8_t abyte = (uint8_t)acqdata.f.ABYTE;
            acq_entries_read++;

            if (signal == I2C_ACQ_SIGNAL_DATA) {
                simputs("    Received ACQ DATA abyte: 0x");
                simputshex32("", abyte);
                simputs("\n");
                if (abyte != REG_ADDR) {
                    simputs("    ERROR: ACQ DATA != REG_ADDR (expected 0x");
                    simputshex32("", REG_ADDR);
                    simputs(")\n");
                    write_scratch(0, 0xBAD00063);
                    test_fail(0);
                }
                found_reg_addr = true;
            } else {
                simputs("    Skipped ACQ signal ");
                simputshex32("", signal);
                simputs(", abyte=0x");
                simputshex32("", abyte);
                simputs("\n");
            }
        } else {
            acq_wait_count++;
            if (acq_wait_count % 1000 == 0) {
                for (volatile int i = 0; i < 100; i++)
                    ;
            }
        }
    }
    if (!found_reg_addr) {
        simputs("    ERROR: Register address not received in ACQ FIFO\n");
        simputshex32("    ACQ entries consumed: ", acq_entries_read);
        simputs("\n");
        simputshex32("    Empty-FIFO polls: ", acq_wait_count);
        simputs("\n");
        if (acq_entries_read >= ACQ_ENTRY_SCAN_LIMIT) {
            /* Entries kept arriving, but none was the register address. */
            simputs("    Cause: entry scan limit reached (ACQ FIFO depth)\n");
            write_scratch(0, 0xBAD00064);
        } else {
            write_scratch(0, 0xBAD00063);
        }
        test_fail(0);
    }

    simputs("  Starting read phase...\n");
    ret = i2c_controller_read(CONTROLLER_IDX, TARGET_ADDR, read_buffer, 2, true);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller read failed\n");
        write_scratch(0, 0xBAD00062);
        test_fail(0);
    }

    read_value = read_buffer[0] | (read_buffer[1] << 8);

    simputs("  Read completed successfully\n");
    simputs("  [VERIFY] Read data verification:\n");
    simputs("    Read data byte[0] (low): 0x");
    simputshex32("", read_buffer[0]);
    simputs("\n");
    simputs("    Read data byte[1] (high): 0x");
    simputshex32("", read_buffer[1]);
    simputs("\n");
    simputs("    Read data (combined): 0x");
    simputshex32("", read_value);
    simputs("\n");
    write_scratch(1, 0x00000061);

    //=========================================================================
    // Step 7: Compare written and read data
    //=========================================================================
    write_scratch(1, 0x00000070);
    simputs("\nStep 7: Compare Written and Read Data\n");
    simputs("  ========================================\n");
    simputs("  [VERIFY] Final Data Comparison:\n");
    simputs("  ========================================\n");
    simputs("    Written data: 0x");
    simputshex32("", TEST_DATA);
    simputs(" (expected)\n");
    simputs("    Read data:   0x");
    simputshex32("", read_value);
    simputs(" (actual)\n");
    simputs("  ========================================\n");

    if (read_value != TEST_DATA) {
        simputs("  [ERROR] Data mismatch detected!\n");
        simputs("    Expected: 0x");
        simputshex32("", TEST_DATA);
        simputs("\n");
        simputs("    Got:      0x");
        simputshex32("", read_value);
        simputs("\n");
        simputs("    Difference: 0x");
        simputshex32("", TEST_DATA ^ read_value);
        simputs("\n");
        write_scratch(0, 0xBAD00070);
        test_fail(0);
    }

    simputs("  [SUCCESS] Data verification PASSED!\n");
    simputs("    Written and read data match perfectly: 0x");
    simputshex32("", TEST_DATA);
    simputs("\n");
    simputs("  ========================================\n");
    write_scratch(1, 0x00000071);

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
    simputs("  - I2C_1 (Target):    @ 0xC0009200, Addr 0x");
    simputshex32("", TARGET_ADDR);
    simputs("\n");
    simputs("  - Register Address:   0x");
    simputshex32("", REG_ADDR);
    simputs("\n");
    simputs("  - Written Data:       0x");
    simputshex32("", TEST_DATA);
    simputs("\n");
    simputs("  - Read Data:          0x");
    simputshex32("", read_value);
    simputs("\n");
    simputs("  - Verification:       PASS\n");
    simputs("\n################################################\n");

    test_pass(0);
}
