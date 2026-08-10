/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C Target Sanity — prove target RX via DUT loopback.
 *
 * I2C_0 controller -> I2C_1 target @ 0x10 (same topology as i2c_p0_rdwr).
 * No external VIP. Secondary harts must NOT re-enter main().
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0
#define TARGET_IDX 1
#define TARGET_ADDR 0x10

static void i2c_wrapper_set(uint32_t idx, bool enable, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = enable ? 1 : 0;
    ctrl.f.I2C_CONTROLLER_MODE_EN = (enable && controller_mode) ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

int main(void) {
    const uint8_t EXPECTED[4] = {0xAA, 0xBB, 0xCC, 0xDD};
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##    I2C Target Sanity Test                 ##\n");
    simputs("##    I2C_0 ctrl -> I2C_1 tgt @ 0x10         ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: Connect I2C_0 ctrl + I2C_1 tgt on shared pads\n");
    i2c_wrapper_set(0, false, true);
    i2c_wrapper_set(1, false, true);
    i2c_wrapper_set(2, false, true);
    i2c_wrapper_set(CONTROLLER_IDX, true, true);
    i2c_wrapper_set(TARGET_IDX, true, false);
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);
    simputs("Step 3: Init controller + target\n");

    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 10,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};
    i2c_timing_config_t timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &timing);
    }

    i2c_controller_config_t ctrl_cfg = {.timing = timing,
                                        .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH,
                                                 .fmt_thresh = I2C_DEFAULT_FMT_THRESH,
                                                 .tx_thresh = 0,
                                                 .acq_thresh = 0},
                                        .enable_interrupts = false,
                                        .timeout_cycles = 0};
    ret = i2c_controller_init(CONTROLLER_IDX, &ctrl_cfg);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
                                   .mask0 = 0x7F,
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = timing,
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
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }

    uint32_t tbase = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t tctrl = {.w = read_reg(tbase + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    tctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(tbase + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                       SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              tctrl.w);
    write_scratch(1, 0x00000031);

    write_scratch(1, 0xEBEDEBE2);
    simputs("Step 4: Write + ACQ verify\n");
    write_scratch(1, 0x00000040);

    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, EXPECTED,
                                                    sizeof(EXPECTED));
    if (ret != I2C_OK) {
        simputs("  ERROR: controller write failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    uint8_t recv[64];
    uint32_t recv_len = 0;
    ret = i2c_target_receive_transaction(TARGET_IDX, recv, sizeof(recv), &recv_len,
                                         I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: target receive failed\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }

    ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: controller idle timeout\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }

    if (recv_len != sizeof(EXPECTED)) {
        simputs("  ERROR: length mismatch got=");
        simputshex32("", recv_len);
        simputs("\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }
    for (uint32_t i = 0; i < sizeof(EXPECTED); i++) {
        if (recv[i] != EXPECTED[i]) {
            simputs("  ERROR: data mismatch\n");
            write_scratch(0, 0xBAD00044);
            test_fail(0);
        }
    }

    i2c_controller_disable(CONTROLLER_IDX);
    i2c_wrapper_set(CONTROLLER_IDX, false, true);
    i2c_wrapper_set(TARGET_IDX, false, false);

    write_scratch(1, 0x00000090);
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* Do NOT define secondary_main here — crt0's weak default dispatches the
 * boot hart into main() and parks other harts. Overriding with a bare WFI
 * leaves every hart parked and the test never starts. */
