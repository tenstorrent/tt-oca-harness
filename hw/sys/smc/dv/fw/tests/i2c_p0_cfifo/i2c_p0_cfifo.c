/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief I2C P0 Controller FMT FIFO Threshold Interrupt Test
 *
 * Verifies the format FIFO threshold interrupt of I2C controller 0: it is
 * asserted while the FIFO level is below the programmed threshold and clears
 * once the level reaches the threshold. The RX FIFO threshold is covered by
 * i2c_p0_fifo.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0
#define FMT_FIFO_THRESHOLD_M 5

static void i2c_wrapper_disable(uint32_t idx) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 0;
    ctrl.f.I2C_CONTROLLER_MODE_EN = 1;
    write_reg(wrapper_addr, ctrl.w);
}

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

/**
 * @brief Check the FMT threshold interrupt below and at the threshold.
 */
static int test_fmt_fifo_empty_threshold(uint32_t idx, uint32_t threshold_m) {
    uint32_t base = i2c_get_base(idx);

    simputs("\n=== Test FMT FIFO Empty Threshold ===\n");
    simputs("  Configuring FMT FIFO threshold to ");
    simputshex32("", threshold_m);
    simputs(" bytes\n");

    i2c__HOST_FIFO_CONFIG_t fifo_cfg = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    fifo_cfg.f.FMT_THRESH = threshold_m;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fifo_cfg.w);

    i2c__HOST_FIFO_CONFIG_t fifo_cfg_verify = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    if (fifo_cfg_verify.f.FMT_THRESH != threshold_m) {
        simputs("  ERROR: FMT threshold not set correctly\n");
        return I2C_ERROR;
    }
    simputs("  FMT threshold verified: ");
    simputshex32("", fifo_cfg_verify.f.FMT_THRESH);
    simputs("\n");

    i2c__INTR_ENABLE_t intr_en = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    intr_en.f.FMT_THRESHOLD = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              intr_en.w);

    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    i2c_controller_disable(idx);
    i2c_reset_fifos(idx, false, true, false, false);
    i2c_controller_enable(idx);

    i2c__HOST_FIFO_STATUS_t fifo_status = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    i2c__INTR_STATE_t intr_state = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    simputs("  FMT FIFO level: ");
    simputshex32("", fifo_status.f.FMTLVL);
    simputs("\n");

    if (threshold_m == 0) {
        simputs("  ERROR: threshold_m must be > 0 for empty-threshold proof\n");
        return I2C_ERROR;
    }
    if (fifo_status.f.FMTLVL >= threshold_m) {
        simputs("  ERROR: FMT FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    if (!intr_state.f.FMT_THRESHOLD) {
        simputs("  ERROR: FMT threshold interrupt should be set when level < threshold\n");
        return I2C_ERROR;
    }

    /* The threshold interrupt is level-sensitive, so filling the FIFO to the
     * threshold must clear it. The controller is disabled so the entries stay
     * in the FIFO instead of going out on the bus. */
    i2c_controller_disable(idx);
    for (uint32_t i = 0; i < threshold_m; i++) {
        i2c__FDATA_t fdata = {.w = 0};
        fdata.f.FBYTE = (uint8_t)(0xA0u + i);
        write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);
    }

    fifo_status.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    intr_state.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                    SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    simputs("  FMT FIFO level after fill: ");
    simputshex32("", fifo_status.f.FMTLVL);
    simputs("\n");

    if (fifo_status.f.FMTLVL < threshold_m) {
        simputs("  ERROR: FMT FIFO did not reach the threshold after pushing\n");
        i2c_reset_fifos(idx, false, true, false, false);
        i2c_controller_enable(idx);
        return I2C_ERROR;
    }
    if (intr_state.f.FMT_THRESHOLD) {
        simputs("  ERROR: FMT threshold interrupt still set with level >= threshold\n");
        i2c_reset_fifos(idx, false, true, false, false);
        i2c_controller_enable(idx);
        return I2C_ERROR;
    }
    simputs("  PASS: FMT threshold interrupt clears when level >= threshold\n");

    i2c_reset_fifos(idx, false, true, false, false);
    i2c_controller_enable(idx);

    simputs("  PASS: FMT threshold interrupt set when FIFO empty (level < threshold)\n");
    return I2C_OK;
}

int main(void) {
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##   I2C P0 Controller FMT Empty Threshold   ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    i2c_wrapper_disable(CONTROLLER_IDX);
    i2c_controller_disable(CONTROLLER_IDX);
    i2c_reset_fifos(CONTROLLER_IDX, true, true, false, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);

    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    i2c_controller_config_t ctrlr_cfg = {.timing = computed_timing,
                                         .fifo = {.rx_thresh = 0,
                                                  .fmt_thresh = FMT_FIFO_THRESHOLD_M,
                                                  .tx_thresh = 0,
                                                  .acq_thresh = 0},
                                         .enable_interrupts = false,
                                         .timeout_cycles = 0};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrlr_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    i2c_reset_fifos(CONTROLLER_IDX, true, true, false, false);

    write_scratch(1, 0x00000040);
    ret = test_fmt_fifo_empty_threshold(CONTROLLER_IDX, FMT_FIFO_THRESHOLD_M);
    if (ret != I2C_OK) {
        simputs("  ERROR: FMT empty-threshold test failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    write_scratch(1, 0x00000041);

    write_scratch(1, 0x00000090);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");
    test_pass(0);
}
