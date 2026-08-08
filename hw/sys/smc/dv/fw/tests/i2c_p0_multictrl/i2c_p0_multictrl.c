/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C P0 Multi-Controller Test — three SMC I2C controllers, shared bus
 *
 * All I2C instances share one SCL/SDA pad pair in this TB. Simultaneous
 * multi-master drive causes X on the pad mux (DebugKnownO_A / sim abort).
 * cocotbext I2cMemory VIP also cannot complete a DUT-controller transfer
 * (open-drain idle); see i2c_p2_concurrent.
 *
 * Proven path: time-multiplex three phases, each with exactly one controller
 * + one DUT target on the bus, write+ACQ verify, then disconnect.
 *
 *   Phase 0: I2C_0 ctrl -> I2C_1 tgt @ 0x30  payload AA BB CC DD
 *   Phase 1: I2C_1 ctrl -> I2C_2 tgt @ 0x31  payload 11 22 33 44
 *   Phase 2: I2C_2 ctrl -> I2C_0 tgt @ 0x32  payload 55 66 77 88
 *
 * Pass: all three phases verify ACQ data; scratch[1]=0xEBEDEBE4 + test_pass.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define I2C_0_IDX 0
#define I2C_1_IDX 1
#define I2C_2_IDX 2

static void i2c_wrapper_set(uint32_t idx, bool enable, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = enable ? 1 : 0;
    ctrl.f.I2C_CONTROLLER_MODE_EN = (enable && controller_mode) ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);
}

static void i2c_disconnect_all(void) {
    i2c_wrapper_set(I2C_0_IDX, false, true);
    i2c_wrapper_set(I2C_1_IDX, false, true);
    i2c_wrapper_set(I2C_2_IDX, false, true);
}

/**
 * One shared-bus write: ctrl_idx -> tgt_idx @ tgt_addr, verify ACQ bytes.
 */
static int i2c_shared_write_verify(uint32_t ctrl_idx, uint32_t tgt_idx, uint8_t tgt_addr,
                                   const uint8_t *data, uint32_t len,
                                   const i2c_timing_config_t *timing) {
    int ret;

    i2c_disconnect_all();

    i2c_wrapper_set(ctrl_idx, true, true);
    i2c_wrapper_set(tgt_idx, true, false);

    i2c_controller_config_t ctrl_cfg = {.timing = *timing,
                                        .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH,
                                                 .fmt_thresh = I2C_DEFAULT_FMT_THRESH,
                                                 .tx_thresh = 0,
                                                 .acq_thresh = 0},
                                        .enable_interrupts = false,
                                        .timeout_cycles = 0};
    ret = i2c_controller_init(ctrl_idx, &ctrl_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: controller init failed\n");
        return ret;
    }

    i2c_target_config_t tgt_cfg = {.address0 = tgt_addr,
                                   .mask0 = 0x7F,
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = *timing,
                                   .fifo = {.tx_thresh = I2C_DEFAULT_TX_THRESH,
                                            .acq_thresh = I2C_DEFAULT_ACQ_THRESH,
                                            .rx_thresh = 0,
                                            .fmt_thresh = 0},
                                   .enable_interrupts = false,
                                   .ack_ctrl_mode = false,
                                   .tx_stretch_ctrl = false,
                                   .timeout_cycles = 0};
    ret = i2c_target_init(tgt_idx, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: target init failed\n");
        return ret;
    }

    /* Enable ACQ START/STOP capture (field, not 1<<7 shift — see rdwr fix). */
    uint32_t tbase = i2c_get_base(tgt_idx);
    i2c__CTRL_t tctrl = {.w = read_reg(tbase + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    tctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(tbase + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                       SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              tctrl.w);

    ret = i2c_controller_write_with_header_nonblock(ctrl_idx, tgt_addr, data, len);
    if (ret != I2C_OK) {
        simputs("  ERROR: controller write failed\n");
        return ret;
    }

    uint8_t recv[64];
    uint32_t recv_len = 0;
    ret =
        i2c_target_receive_transaction(tgt_idx, recv, sizeof(recv), &recv_len, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: target receive failed\n");
        return ret;
    }

    ret = i2c_controller_wait_idle(ctrl_idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        simputs("  ERROR: controller did not go idle\n");
        return ret;
    }

    if (recv_len != len) {
        simputs("  ERROR: received length mismatch\n");
        return I2C_ERROR_INVALID;
    }
    for (uint32_t i = 0; i < len; i++) {
        if (recv[i] != data[i]) {
            simputs("  ERROR: received data mismatch\n");
            return I2C_ERROR_INVALID;
        }
    }

    i2c_controller_disable(ctrl_idx);
    i2c_disconnect_all();
    return I2C_OK;
}

int main(void) {
    int ret;
    uint8_t phase0_data[4] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t phase1_data[4] = {0x11, 0x22, 0x33, 0x44};
    uint8_t phase2_data[4] = {0x55, 0x66, 0x77, 0x88};

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Multi-Controller Test            ##\n");
    simputs("##   Time-multiplexed 3-controller paths     ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    write_scratch(1, 0x00000011);

    write_scratch(1, 0x00000020);
    simputs("Step 2: Compute shared I2C timing\n");
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
    write_scratch(1, 0x00000021);

    /* Ready marker for TB (VIP not used — internal loopback). */
    write_scratch(1, 0xEBEDEBE2);
    simputs("Step 3: Three phases (ctrl+tgt pairs on shared bus)\n");

    write_scratch(1, 0x00000030);
    simputs("  Phase 0: I2C_0 ctrl -> I2C_1 tgt @ 0x30\n");
    ret = i2c_shared_write_verify(I2C_0_IDX, I2C_1_IDX, 0x30, phase0_data, sizeof(phase0_data),
                                  &computed_timing);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    write_scratch(1, 0x00000031);

    write_scratch(1, 0x00000040);
    simputs("  Phase 1: I2C_1 ctrl -> I2C_2 tgt @ 0x31\n");
    ret = i2c_shared_write_verify(I2C_1_IDX, I2C_2_IDX, 0x31, phase1_data, sizeof(phase1_data),
                                  &computed_timing);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    write_scratch(1, 0x00000041);

    write_scratch(1, 0x00000050);
    simputs("  Phase 2: I2C_2 ctrl -> I2C_0 tgt @ 0x32\n");
    ret = i2c_shared_write_verify(I2C_2_IDX, I2C_0_IDX, 0x32, phase2_data, sizeof(phase2_data),
                                  &computed_timing);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }
    write_scratch(1, 0x00000051);

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
