/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p0_timeout.c
 * @brief I2C P0 controller stretch-timeout observation test
 *
 * I2C_1 (controller) reads from I2C_0 (target) while the target's TX FIFO is
 * empty, so the target stretches the clock. The test checks that the
 * controller's stretch-timeout interrupt asserts, and that it clears once the
 * target is disabled to end the stretch. Controller recovery after the timeout
 * is covered by i2c_tx_stretch_timeout_recovery.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define TARGET_IDX 0
#define CONTROLLER_IDX 1
#define TARGET_ADDR 0x10
#define READ_STRETCH_TIMEOUT_CYCLES 2000
#define POLL_TIMEOUT 100000

/* Bound on retrying the W1C once the stretch has been released. Each iteration
 * is a register write plus a read, so this covers well past the bus time the
 * controller FSM needs to leave the stretched state. */
#define W1C_CLEAR_POLL_BOUND 20000u

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(0) + (idx * 4);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

static void get_test_timing(i2c_timing_config_t *timing) {
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    if (i2c_compute_timing_from_physical(&physical_params, timing) != I2C_OK) {
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
                                              .timeout_cycles = READ_STRETCH_TIMEOUT_CYCLES};

    int ret = i2c_controller_init(CONTROLLER_IDX, &controller_cfg);
    if (ret != I2C_OK) {
        return ret;
    }

    i2c_config_timeout(CONTROLLER_IDX, READ_STRETCH_TIMEOUT_CYCLES, true, true);

    /* Enable the stretch-timeout interrupt so its state can be polled */
    uint32_t base = i2c_get_base(CONTROLLER_IDX);
    i2c__INTR_ENABLE_t intr_en = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr_en.f.STRETCH_TIMEOUT = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_en.w);
    i2c_clear_interrupts(CONTROLLER_IDX, 0xFFFFFFFF);

    /* The interrupt must read clear before the stretch, or a bit stuck set
     * would satisfy the poll below without any timeout. */
    {
        i2c__INTR_STATE_t after_clear = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        simputs("  Baseline after clear: INTR_STATE=");
        simputshex32("", after_clear.w);
        simputs("\n");
        if (after_clear.f.STRETCH_TIMEOUT) {
            simputs("  ERROR: stretch_timeout already set before any stretch --\n");
            simputs("         the poll below would prove nothing\n");
            return I2C_ERROR;
        }
    }

    return I2C_OK;
}

static int init_target(void) {
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

    int ret = i2c_target_init(TARGET_IDX, &target_cfg);
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
    i2c_reset_fifos(TARGET_IDX, false, false, true, true);
    return I2C_OK;
}

static int enqueue_controller_read_one_byte(void) {
    uint32_t base = i2c_get_base(CONTROLLER_IDX);

    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        i2c__HOST_FIFO_STATUS_t fifo_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if ((64u - fifo_status.f.FMTLVL) >= 2u) {
            break;
        }
        if (i + 1u == POLL_TIMEOUT) {
            simputs("  ERROR: FMT FIFO space timeout\n");
            return I2C_ERROR_TIMEOUT;
        }
    }

    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = (TARGET_ADDR << 1) | 0x1;
    fdata.f.START = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    fdata.w = 0;
    fdata.f.FBYTE = 1;
    fdata.f.READB = 1;
    fdata.f.STOP = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);
    return I2C_OK;
}

static int wait_stretch_timeout_intr(void) {
    uint32_t base = i2c_get_base(CONTROLLER_IDX);

    simputs("  Polling INTR_STATE.stretch_timeout...\n");
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        i2c__INTR_STATE_t intr = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (intr.f.STRETCH_TIMEOUT) {
            simputs("  PASS: stretch_timeout interrupt asserted\n");
            simputshex32("  INTR_STATE=", intr.w);
            simputs("\n");

            /* The clear must also work, or a bit stuck set cannot be told from
             * a real event. The timeout event is a level that holds for as long
             * as the target stretches and sets the interrupt again after each
             * clear, so end the stretch before clearing. */
            i2c_target_disable(TARGET_IDX);
            {
                i2c__INTR_STATE_t after = {.w = 0};
                uint32_t tries = 0;

                /* The controller needs bus time to leave the stretched state
                 * after the disable, so retry the clear up to a bound. A bit
                 * stuck set exhausts the bound and fails. */
                for (tries = 0; tries < W1C_CLEAR_POLL_BOUND; tries++) {
                    i2c_clear_interrupts(CONTROLLER_IDX, 0xFFFFFFFF);
                    after.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                               SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                    if (!after.f.STRETCH_TIMEOUT) {
                        break;
                    }
                }

                simputs("  After stretch release + W1C: INTR_STATE=");
                simputshex32("", after.w);
                simputs(" tries=");
                simputshex32("", tries);
                simputs("\n");
                if (after.f.STRETCH_TIMEOUT) {
                    simputs("  ERROR: stretch_timeout did not clear on W1C after the\n");
                    simputs("         stretch was released; the bit is stuck set\n");
                    return I2C_ERROR;
                }
            }
            return I2C_OK;
        }
    }

    i2c__INTR_STATE_t last = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    simputs("  ERROR: stretch_timeout not observed, INTR_STATE=");
    simputshex32("", last.w);
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

int main(void) {
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Stretch Timeout Observation      ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    i2c_wrapper_enable(TARGET_IDX, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    ret = init_target();
    if (ret != I2C_OK) {
        simputs("  ERROR: target init failed\n");
        write_scratch(0, 0xBAD00010);
        test_fail(0);
    }
    ret = init_controller();
    if (ret != I2C_OK) {
        simputs("  ERROR: controller init failed\n");
        write_scratch(0, 0xBAD00011);
        test_fail(0);
    }

    write_scratch(1, 0x00000020);
    simputs("  Enqueue READ with empty target TX (expect stretch timeout)...\n");
    ret = enqueue_controller_read_one_byte();
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00020);
        test_fail(0);
    }

    write_scratch(1, 0x00000030);
    ret = wait_stretch_timeout_intr();
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }

    /* Release the bus for a clean end */
    write_scratch(1, 0x00000040);
    i2c_target_disable(TARGET_IDX);
    i2c_controller_disable(CONTROLLER_IDX);

    write_scratch(1, 0xEBEDEBE6);
    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Stretch Timeout Observation PASS ##\n");
    simputs("################################################\n");
    test_pass(0);
}
