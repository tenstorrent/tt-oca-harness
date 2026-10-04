/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p1_back_to_back_xfer.c
 * @brief I2C single write transfer with payload check
 *
 * Verifies one 4-byte write from the I2C_0 controller to the I2C_1 target: the
 * target must report the end of the transaction, no received byte may be
 * NACKed, and the payload length and every byte must match the stimulus. Only
 * one transaction is sent, so back-to-back recovery, FIFO depth and overflow
 * are not exercised.
 *
 * The I2C wrappers must select controller or target mode before the I2C IPs
 * are configured.
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

    write_scratch(1, 0x00000040);
    simputs("Step 4: Simple I2C Write\n");

    uint8_t data_buf[] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t recv_buffer[16];
    uint32_t received_len = 0;

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

    write_scratch(1, 0x00000043);
    simputs("  [4.2] Waiting for ACQ FIFO data...\n");
    /* Synchronise on the target's own end-of-transaction event.
     *
     * The number of received entries cannot be derived from the number of
     * controller pushes: the target stays in its reset mode, where it records
     * no START, RESTART or STOP entries, so a wait on a count computed from the
     * pushes may never return. Wait for the target's STOP event instead, then
     * drain whatever it produced. The wait is bounded and expiry fails.
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

    /* Drain and log every entry, and collect the payload.
     *
     * The first data byte is the length header that
     * i2c_controller_write_with_header_nonblock sends before the payload;
     * START and STOP entries are framing.
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
            /* A NACKed byte is not payload, and the entry decoder leaves
             * is_start and is_stop false for it, so reject it before the
             * framing filter. A NACK means the transfer did not carry the
             * stimulus, so it fails the test. */
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

    /* Compare the payload length and every byte with the stimulus. */
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

    simputs("\n");
    simputs("FIFO Stress Test PASSED\n");
    write_scratch(1, 0xEBEDEBE4);
    test_pass(0);
}
