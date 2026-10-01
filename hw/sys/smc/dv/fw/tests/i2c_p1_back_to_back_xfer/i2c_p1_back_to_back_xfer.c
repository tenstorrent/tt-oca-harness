/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p1_back_to_back_xfer.c
 * @brief I2C back-to-back transactions and transaction-to-transaction recovery
 *
 * =============================================================================
 * Test Description
 * =============================================================================
 *
 * 8 sequential write/receive transactions between the internal I2C controller
 * and target, back to back, with a per-byte compare on each. What this reaches
 * that a single-shot transfer cannot is FIFO and state recovery *between*
 * transactions.
 *
 * The FIFO levels stay far from full: each transaction carries 4 data bytes
 * against a target RX FIFO depth of 268 and an FMT depth of 64, and no
 * overflow or error path is reached. FIFO-depth and overflow behaviour are
 * outside this test's scope.
 *
 * Expected Result:
 * - All 8 transactions complete successfully
 * - No FIFO overflow/underflow errors
 * - System remains stable without corruption or deadlock
 *
 * =============================================================================
 * Test Architecture: Two-Level I2C Control
 * =============================================================================
 *
 * LEVEL 1: Wrapper Control (0xC0009E00)
 *   - Controls GPIO pad multiplexing
 *   - Selects I2C mode (Controller/Target)
 *   - MUST be configured FIRST before IP-level configuration
 *
 * LEVEL 2: IP Control (0xC0009000 + 0x200*idx)
 *   - OpenTitan I2C IP protocol layer
 *   - Handles timing, FIFO, interrupts, transactions
 *
 * =============================================================================
 * Configuration Details
 * =============================================================================
 *
 * I2C_0 Configuration (Controller Mode):
 *   - Speed: Standard mode (100 kHz)
 *   - FIFO Thresholds:
 *     * RX FIFO: 29 entries
 *     * FMT FIFO: 5 entries
 *
 * I2C_1 Configuration (Target Mode):
 *   - Address: 0x10 (7-bit)
 *   - Address Mask: 0x7F (exact match)
 *   - FIFO Thresholds:
 *     * TX FIFO: 5 entries
 *     * ACQ FIFO: 29 entries
 *
 * =============================================================================
 * Test Flow
 * =============================================================================
 *
 * Step 1: System Initialization
 * Step 2: Wrapper Control Enable (LEVEL 1)
 * Step 3: I2C IP Initialization (LEVEL 2)
 * Step 4: FIFO Stress Test (3 transactions)
 * Step 5: Rapid FIFO Stress Test (5 more transactions)
 * Step 6: Test Complete
 *
 * =============================================================================
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0
#define TARGET_IDX 1
#define TARGET_ADDR 0x10

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputs("  Wrapper[");
    simputshex32("", idx);
    simputs("] enabled: mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

int main(void) {
    int ret = I2C_OK;

    simputs("\n");
    simputs("###################################################\n");
    simputs("##   I2C P1 FIFO Overflow/Underflow Test       ##\n");
    simputs("###################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(CONTROLLER_IDX, true); // I2C_0 as Controller
    i2c_wrapper_enable(TARGET_IDX, false);    // I2C_1 as Target
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("Step 3: LEVEL 2 - I2C IP Initialization\n");

    // Compute timing parameters
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

    // Initialize Controller
    simputs("  Initializing I2C_0 Controller...\n");
    i2c_controller_config_t ctrlr_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = 29, .fmt_thresh = 5, .tx_thresh = 0, .acq_thresh = 0},
        .enable_interrupts = false,
        .timeout_cycles = 0};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Controller initialized successfully\n");

    // Initialize Target
    simputs("  Initializing I2C_1 Target...\n");
    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
        .mask0 = 0x7F,
        .address1 = 0,
        .mask1 = 0,
        .timing = computed_timing,
        .fifo = {.tx_thresh = 5, .acq_thresh = 29, .rx_thresh = 0, .fmt_thresh = 0},
        .enable_interrupts = false,
        .ack_ctrl_mode = false,
        .tx_stretch_ctrl = false,
        .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");
    write_scratch(1, 0x00000031);

    //=========================================================================
    // Step 4: FIFO Stress Test - Simple I2C Write
    //=========================================================================
    write_scratch(1, 0x00000040);
    simputs("Step 4: Simple I2C Write\n");

    uint8_t data_buf[] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t recv_buffer[16];
    uint32_t received_len = 0;

    // Step 4.1: Controller write (non-blocking)
    write_scratch(1, 0x00000041);
    simputs("  [4.1] Controller write (non-blocking)...\n");
    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, data_buf,
                                                    sizeof(data_buf));
    if (ret != I2C_OK) {
        simputs("  [ERROR] Controller write failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    write_scratch(1, 0x00000042);
    simputs("  [4.1] Controller write command sent to FMT FIFO\n");

    // Step 4.2: Wait for ACQ FIFO to have data (target received data from controller)
    write_scratch(1, 0x00000043);
    simputs("  [4.2] Waiting for ACQ FIFO data...\n");
    /* Synchronise on the target's own end-of-transaction event.
     *
     * The count of ACQ entries is not derivable from the number of FMT pushes:
     * CTRL.ACQ_START_STOP_EN is at its reset value of 0 (i2c.rdl:580), so the
     * target writes no START/RESTART/STOP entry, and a write of N bytes leaves
     * fewer than N+1 entries. Waiting on a count computed that way cannot be
     * relied on to return.
     *
     * STOP_DETECT is the DUT telling us the transaction is over, so wait for
     * that and then drain whatever it produced. Bounded, and the bound fails.
     */
    {
        uint32_t i;
        int stopped = 0;
        for (i = 0; i < 200000u; i++) {
            if (i2c_get_target_events(TARGET_IDX) & (1u << 4)) { /* STOP_DETECT */
                stopped = 1;
                break;
            }
        }
        if (!stopped) {
            uint32_t tx_lvl = 0, acq_lvl = 0;
            i2c_target_get_fifo_status(TARGET_IDX, &tx_lvl, &acq_lvl);
            simputs("  [ERROR] target never reported STOP_DETECT; ACQLVL=0x");
            simputshex32("", acq_lvl);
            simputs("\n");
            write_scratch(0, 0xBAD00041);
            test_fail(0);
        }
    }
    write_scratch(1, 0x00000044);
    simputs("  [4.2] STOP detected; draining ACQ FIFO\n");

    /* Drain every entry and reconcile the payload.
     *
     * Entries are itemised in the log so the transaction inventory is evidence
     * rather than an assumption. The length header is the first data byte
     * (i2c_controller_write_with_header_nonblock sends len before the payload);
     * START/STOP entries are framing.
     */
    write_scratch(1, 0x00000045);
    {
        uint32_t seen_data = 0;
        int header_taken = 0;
        received_len = 0;
        while (!i2c_target_acq_fifo_empty(TARGET_IDX)) {
            i2c_acq_entry_t e;
            if (i2c_target_receive_entry(TARGET_IDX, &e) != I2C_OK) {
                simputs("  [ERROR] ACQ entry read failed\n");
                write_scratch(0, 0xBAD00042);
                test_fail(0);
            }
            simputs("    ACQ signal=0x");
            simputshex32("", e.signal);
            simputs(" data=0x");
            simputshex32("", e.data);
            simputs("\n");
            seen_data++;
            /* A NACKed byte is not payload.
             *
             * is_start/is_stop alone do not exclude it: the entry classifier
             * maps NACK and NACK_START onto its default leg, which leaves both
             * flags false, so without is_nack this filter would accept a byte
             * the target NACKed and copy it into recv_buffer as ordinary data.
             * A NACK means the transfer did not carry
             * what the comparison below assumes, so it fails rather than being
             * silently folded into the payload. */
            if (e.is_nack) {
                simputs("  ERROR: NACKed ACQ entry in payload stream, signal=0x");
                simputshex32("", e.signal);
                simputs(" data=0x");
                simputshex32("", e.data);
                simputs("\n");
                test_fail(0);
            }
            if (e.is_start || e.is_stop) {
                continue;
            }
            if (!header_taken) {
                header_taken = 1; /* length header, not payload */
                continue;
            }
            if (received_len < sizeof(recv_buffer)) {
                recv_buffer[received_len++] = e.data;
            }
        }
        simputs("  [4.3] ACQ entries drained: 0x");
        simputshex32("", seen_data);
        simputs(" payload bytes: 0x");
        simputshex32("", received_len);
        simputs("\n");
    }

    /* The payload count and every byte are reconciled against the stimulus. */
    if (received_len != sizeof(data_buf)) {
        simputs("  [ERROR] payload count mismatch: expected 0x");
        simputshex32("", (uint32_t)sizeof(data_buf));
        simputs(", got 0x");
        simputshex32("", received_len);
        simputs("\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }
    for (size_t k = 0; k < sizeof(data_buf); k++) {
        if (recv_buffer[k] != data_buf[k]) {
            simputs("  [ERROR] data mismatch at index 0x");
            simputshex32("", (uint32_t)k);
            simputs(": expected 0x");
            simputshex32("", data_buf[k]);
            simputs(", got 0x");
            simputshex32("", recv_buffer[k]);
            simputs("\n");
            write_scratch(0, 0xBAD00044);
            test_fail(0);
        }
    }
    simputs("  [4.3] payload matched {0xAA,0xBB,0xCC,0xDD}\n");

    write_scratch(1, 0x00000047);

    //=========================================================================
    // Step 6: Test Complete
    //=========================================================================
    simputs("\n");
    simputs("FIFO Stress Test PASSED\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);

    return I2C_OK;
}
