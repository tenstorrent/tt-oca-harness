/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C target ACQ FIFO automatic stretch release test
 *
 * I2C_1 acts as controller and writes more data than I2C_0 target can accept
 * without firmware service. The target ACQ FIFO reaches the automatic stretch
 * threshold, firmware resets ACQ directly, then a second short write is received
 * and checked by firmware.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define TARGET_IDX 0
#define CONTROLLER_IDX 1
#define TARGET_ADDR 0x10
#define ACQ_FIFO_DEPTH 64
#define ACQ_STRETCH_LEVEL (ACQ_FIFO_DEPTH - 2)
#define LONG_WRITE_LEN 70
#define VERIFY_WRITE_LEN 4
#define POLL_TIMEOUT 10000
/* Short probe before forcing target disable (in-transaction after long write). */
#define TARGET_IDLE_PROBE 256

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

static uint32_t get_acq_level(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__TARGET_FIFO_STATUS_t fifo_status = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    return fifo_status.f.ACQLVL;
}

static i2c__STATUS_t get_i2c_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    return status;
}

static int wait_for_acq_stretch_level(uint32_t idx) {
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        i2c__STATUS_t status = get_i2c_status(idx);
        uint32_t acqlvl = get_acq_level(idx);

        if (status.f.ACQFULL || acqlvl >= ACQ_STRETCH_LEVEL) {
            simputs("  Target ACQ reached stretch threshold, acqlvl=0x");
            simputshex32("", acqlvl);
            simputs("\n");
            return I2C_OK;
        }
    }

    simputs("  ERROR: Timed out waiting for target ACQ stretch threshold, acqlvl=0x");
    simputshex32("", get_acq_level(idx));
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

static int wait_for_acq_empty(uint32_t idx) {
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        i2c__STATUS_t status = get_i2c_status(idx);
        uint32_t acqlvl = get_acq_level(idx);

        if (status.f.ACQEMPTY && acqlvl == 0) {
            return I2C_OK;
        }
    }

    simputs("  ERROR: Timed out waiting for target ACQ empty, acqlvl=0x");
    simputshex32("", get_acq_level(idx));
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

static int wait_for_target_idle(uint32_t idx) {
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        if (i2c_target_is_idle(idx)) {
            return I2C_OK;
        }
    }

    simputs("  ERROR: Timed out waiting for target idle, status=0x");
    simputshex32("", get_i2c_status(idx).w);
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

static int probe_target_idle(uint32_t idx, uint32_t max_iters) {
    for (uint32_t i = 0; i < max_iters; i++) {
        if (i2c_target_is_idle(idx)) {
            return I2C_OK;
        }
    }
    return I2C_ERROR_TIMEOUT;
}

static int clear_controller_events_and_wait(uint32_t idx) {
    i2c_clear_controller_events(idx, 0xFFFFFFFF);

    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        uint32_t events = i2c_get_controller_events(idx);

        if (events == 0) {
            return I2C_OK;
        }
    }

    simputs("  ERROR: Timed out clearing controller events, events=0x");
    simputshex32("", i2c_get_controller_events(idx));
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

static void clear_target_acq_fifo(uint32_t idx) {
    i2c_reset_fifos(idx, false, false, false, true);
    for (volatile uint32_t i = 0; i < 1000; i++) {
        __asm__("nop");
    }
}

static void get_test_timing(i2c_timing_config_t *timing) {
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 10,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    int ret = i2c_compute_timing_from_physical(&physical_params, timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, timing);
    }
}

static int init_controller(void) {
    i2c_timing_config_t timing;
    get_test_timing(&timing);

    i2c_controller_config_t controller_cfg = {.timing = timing,
                                              .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH,
                                                       .fmt_thresh = I2C_DEFAULT_FMT_THRESH,
                                                       .tx_thresh = 0,
                                                       .acq_thresh = 0},
                                              .enable_interrupts = false,
                                              .timeout_cycles = 0};

    return i2c_controller_init(CONTROLLER_IDX, &controller_cfg);
}

static int init_target(void) {
    int ret;
    i2c_timing_config_t timing;
    get_test_timing(&timing);

    i2c_target_config_t target_cfg = {.address0 = TARGET_ADDR,
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

    ret = i2c_target_init(TARGET_IDX, &target_cfg);
    if (ret != I2C_OK) {
        return ret;
    }

    uint32_t target_base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t target_ctrl = {
        .w = read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    target_ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              target_ctrl.w);

    return I2C_OK;
}

static int init_i2c_pair(void) {
    int ret;

    i2c_wrapper_enable(TARGET_IDX, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    ret = init_target();
    if (ret != I2C_OK) {
        return ret;
    }

    return init_controller();
}

static int send_long_write_until_target_stretches(void) {
    uint8_t long_data[LONG_WRITE_LEN];

    for (uint32_t i = 0; i < LONG_WRITE_LEN; i++) {
        long_data[i] = (uint8_t)(0x40u + i);
    }

    simputs("  Controller sending long write to fill target ACQ FIFO...\n");
    int ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, long_data,
                                                        LONG_WRITE_LEN);
    if (ret != I2C_OK) {
        simputs("  Long write enqueue returned 0x");
        simputshex32("", (uint32_t)ret);
        simputs("; checking ACQ stretch threshold anyway\n");
    }

    return wait_for_acq_stretch_level(TARGET_IDX);
}

static int release_stretch_and_discard_long_write_tail(void) {
    int ret;

    /*
     * Proof stimulus: ACQ FIFO reset releases automatic SCL stretch.
     * Then recover the in-progress long write like tx_stretch_timeout_recovery
     * (controller disable → STOP, target disable → idle, reinit both).
     * ACQ reset + controller disable must be back-to-back — any simputs gap
     * lets FMT drain more bytes into ACQ and keep targetidle clear.
     */
    simputs("  ACQ reset (stretch release) then controller disable...\n");
    i2c_reset_fifos(TARGET_IDX, false, false, false, true);
    i2c_controller_disable(CONTROLLER_IDX);

    simputs("  Waiting for controller idle after automatic STOP recovery...\n");
    ret = i2c_controller_wait_idle(CONTROLLER_IDX, POLL_TIMEOUT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller did not become idle after stretch release\n");
        return ret;
    }

    clear_target_acq_fifo(TARGET_IDX);
    if (probe_target_idle(TARGET_IDX, TARGET_IDLE_PROBE) != I2C_OK) {
        simputs("  Target still in-transaction; disabling target...\n");
        i2c_target_disable(TARGET_IDX);
        clear_target_acq_fifo(TARGET_IDX);
    }

    ret = wait_for_target_idle(TARGET_IDX);
    if (ret != I2C_OK) {
        return ret;
    }

    simputs("  Clearing controller events after stretch recovery...\n");
    ret = clear_controller_events_and_wait(CONTROLLER_IDX);
    if (ret != I2C_OK) {
        return ret;
    }

    i2c_reset_fifos(CONTROLLER_IDX, true, true, false, false);
    i2c_reset_fifos(TARGET_IDX, false, false, true, true);

    simputs("  Reinitializing target+controller after stretch recovery...\n");
    ret = init_target();
    if (ret != I2C_OK) {
        simputs("  ERROR: Target reinitialization failed\n");
        return ret;
    }
    ret = init_controller();
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller reinitialization failed\n");
        return ret;
    }

    simputs("  Clearing target ACQ FIFO after discarded long write tail...\n");
    clear_target_acq_fifo(TARGET_IDX);
    return wait_for_acq_empty(TARGET_IDX);
}

static int send_and_check_verify_write(void) {
    const uint8_t expected[VERIFY_WRITE_LEN] = {0xA5, 0x5A, 0xC3, 0x3C};
    uint8_t received[16] = {0};
    uint32_t received_len = 0;

    simputs("  Controller sending verification write...\n");
    int ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, expected,
                                                        VERIFY_WRITE_LEN);
    if (ret != I2C_OK) {
        simputs("  ERROR: Verification write enqueue failed\n");
        return ret;
    }

    ret = i2c_target_receive_transaction(TARGET_IDX, received, sizeof(received), &received_len,
                                         POLL_TIMEOUT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target receive failed for verification write\n");
        return ret;
    }

    if (received_len != VERIFY_WRITE_LEN) {
        simputs("  ERROR: Verification length mismatch, got 0x");
        simputshex32("", received_len);
        simputs("\n");
        return I2C_ERROR;
    }

    for (uint32_t i = 0; i < VERIFY_WRITE_LEN; i++) {
        if (received[i] != expected[i]) {
            simputs("  ERROR: Verification data mismatch at index 0x");
            simputshex32("", i);
            simputs(", got 0x");
            simputshex32("", received[i]);
            simputs(", expected 0x");
            simputshex32("", expected[i]);
            simputs("\n");
            return I2C_ERROR;
        }
    }

    ret = i2c_controller_wait_idle(CONTROLLER_IDX, POLL_TIMEOUT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller did not become idle after verification write\n");
        return ret;
    }

    simputs("  Verification write received and matched\n");
    return I2C_OK;
}

int main(void) {
    int ret;

    simputs("\n");
    simputs("########################################################\n");
    simputs("## I2C ACQ FIFO Auto Stretch Reset Test              ##\n");
    simputs("########################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    ret = init_i2c_pair();
    if (ret != I2C_OK) {
        simputs("ERROR: I2C pair initialization failed\n");
        write_scratch(0, 0xBAD00010);
        test_fail(0);
    }

    write_scratch(1, 0x00000020);
    ret = send_long_write_until_target_stretches();
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00020);
        test_fail(0);
    }

    write_scratch(1, 0x00000030);
    ret = release_stretch_and_discard_long_write_tail();
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    write_scratch(1, 0x00000040);
    ret = send_and_check_verify_write();
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("########################################################\n");
    simputs("## I2C ACQ FIFO Auto Stretch Reset Test PASSED       ##\n");
    simputs("########################################################\n");
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}
