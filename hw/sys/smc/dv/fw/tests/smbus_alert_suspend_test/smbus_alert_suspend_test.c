/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief SMBus ALERT / SUSPEND — DUT-internal OpenTitan I2C loopback.
 *
 * I2C_0 Target asserts SMBALERT#; I2C_1 Controller detects, ARA-clears, then
 * asserts SMBSUS# which the Target observes on SMBUS_STATUS.
 * Both I2C instances are looped back inside the DUT; secondary_main is the crt0 weak default.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define TARGET_IDX 0u
#define CONTROLLER_IDX 1u
#define TARGET_ADDR 0x10u
#define WAIT_MAX 50000u

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(0) + (idx * 4);
    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};

    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    ctrl.f.SMBUS_EN = 1;
    write_reg(wrapper_addr, ctrl.w);
}

static void i2c_wrapper_disable_all(void) {
    for (uint32_t i = 0; i < 3; i++) {
        uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(0) + (i * 4);
        write_reg(wrapper_addr, 0);
    }
}

static bool wait_until(bool (*cond_fn)(uint32_t), uint32_t idx, bool expected, uint32_t timeout) {
    while (timeout--) {
        if (cond_fn(idx) == expected) {
            return true;
        }
        for (volatile uint32_t i = 0; i < 50; i++) {
        }
    }
    return false;
}

static bool smbus_host_alert_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__SMBUS_STATUS_t st = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return st.f.SMBALERT ? true : false;
}

static bool smbus_host_alert_irq(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t intr = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return intr.f.SMBALERT == 1;
}

static void smbus_clear_host_alert_irq(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_STATE_t clr = {.w = 0};
    clr.f.SMBALERT = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              clr.w);
}

static void smbus_enable_host_alert_irq(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__INTR_ENABLE_t en = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    en.f.SMBALERT = 1;
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              en.w);
}

static bool smbus_device_suspend_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__SMBUS_STATUS_t st = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return st.f.SMBSUS ? true : false;
}

static bool smbus_target_alert_ctrl(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__SMBUS_CTRL_t ctrl = {
        .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return ctrl.f.SMBALERT ? true : false;
}

int main(void) {
    int ret;
    uint8_t alert_addr = 0;
    uint8_t target_addr_byte;
    uint32_t written;

    simputs("[SMBUS] smbus_alert_suspend_test: start (OT I2C DUT loopback)\n");
    write_scratch(1, 0x00000010);

    i2c_wrapper_disable_all();
    i2c_wrapper_enable(TARGET_IDX, false);
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    write_scratch(1, 0x00000020);

    i2c_timing_physical_t physical = {.speed = I2C_SPEED_STANDARD,
                                      .clock_period_nanos = 10,
                                      .sda_rise_nanos = 300,
                                      .sda_fall_nanos = 100,
                                      .scl_period_nanos = 0};
    i2c_timing_config_t timing;
    ret = i2c_compute_timing_from_physical(&physical, &timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &timing);
    }

    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
                                   .mask0 = 0x7F,
                                   .address1 = SMBUS_ADDR_ARA,
                                   .mask1 = 0x7F,
                                   .timing = timing,
                                   .fifo = {.tx_thresh = 1,
                                            .acq_thresh = I2C_DEFAULT_ACQ_THRESH,
                                            .rx_thresh = 0,
                                            .fmt_thresh = 0},
                                   .enable_interrupts = false,
                                   .ack_ctrl_mode = false,
                                   .tx_stretch_ctrl = false,
                                   .timeout_cycles = 0};
    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("[SMBUS] ERROR: target init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
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
        simputs("[SMBUS] ERROR: controller init failed\n");
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }

    smbus_enable_host_alert_irq(CONTROLLER_IDX);
    smbus_clear_host_alert_irq(CONTROLLER_IDX);
    i2c_smbus_alert(TARGET_IDX, false);
    i2c_smbus_suspend(CONTROLLER_IDX, false);
    write_scratch(1, 0x00000030);
    simputs("[SMBUS] Initial state cleared (ALERT=0, SUSPEND=0)\n");

    /* ---- ALERT: Device -> Host ---- */
    write_scratch(1, 0x00000040);
    simputs("[SMBUS][ALERT] Device asserts ALERT -> expect Host detect + IRQ\n");
    i2c_smbus_alert(TARGET_IDX, true);

    if (!wait_until(smbus_host_alert_status, CONTROLLER_IDX, true, WAIT_MAX)) {
        simputs("[SMBUS] ERROR: ALERT did not propagate Device->Host\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    if (!wait_until(smbus_host_alert_irq, CONTROLLER_IDX, true, WAIT_MAX)) {
        simputs("[SMBUS] ERROR: ALERT IRQ not observed on Host\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    simputs("[SMBUS][ALERT] Host status=1 / IRQ seen\n");

    if (!smbus_target_alert_ctrl(TARGET_IDX)) {
        simputs("[SMBUS] ERROR: Target SMBALERT ctrl cleared before ARA\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }

    target_addr_byte = (uint8_t)(TARGET_ADDR << 1);
    written = i2c_target_transmit(TARGET_IDX, &target_addr_byte, 1);
    if (written != 1) {
        simputs("[SMBUS] ERROR: failed to load Target TX for ARA\n");
        write_scratch(0, 0xBAD00043);
        test_fail(0);
    }

    ret = smbus_alert_response(CONTROLLER_IDX, &alert_addr);
    if (ret != I2C_OK) {
        simputs("[SMBUS] ERROR: ARA read failed\n");
        write_scratch(0, 0xBAD00044);
        test_fail(0);
    }
    if (alert_addr != TARGET_ADDR) {
        simputs("[SMBUS] ERROR: ARA address mismatch\n");
        simputshex32("  got=", alert_addr);
        simputs("\n");
        write_scratch(0, 0xBAD00045);
        test_fail(0);
    }

    if (!wait_until(smbus_target_alert_ctrl, TARGET_IDX, false, WAIT_MAX)) {
        simputs("[SMBUS] ERROR: Target did not auto-clear SMBALERT after ARA\n");
        write_scratch(0, 0xBAD00046);
        test_fail(0);
    }
    smbus_clear_host_alert_irq(CONTROLLER_IDX);
    if (!wait_until(smbus_host_alert_status, CONTROLLER_IDX, false, WAIT_MAX)) {
        simputs("[SMBUS] ERROR: Host ALERT status did not clear after ARA\n");
        write_scratch(0, 0xBAD00047);
        test_fail(0);
    }
    simputs("[SMBUS][ALERT] ARA done; Host status cleared\n");
    write_scratch(1, 0x00000041);

    /* ---- SUSPEND: Host -> Device ---- */
    write_scratch(1, 0x00000050);
    simputs("[SMBUS][SUSPEND] Host asserts SUSPEND -> expect Device status=1\n");
    i2c_smbus_suspend(CONTROLLER_IDX, true);
    if (!wait_until(smbus_device_suspend_status, TARGET_IDX, true, WAIT_MAX)) {
        simputs("[SMBUS] ERROR: SUSPEND did not propagate Host->Device\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }
    simputs("[SMBUS][SUSPEND] Device status=1\n");

    i2c_smbus_suspend(CONTROLLER_IDX, false);
    if (!wait_until(smbus_device_suspend_status, TARGET_IDX, false, WAIT_MAX)) {
        simputs("[SMBUS] ERROR: SUSPEND deassert did not clear Device status\n");
        write_scratch(0, 0xBAD00051);
        test_fail(0);
    }
    simputs("[SMBUS][SUSPEND] Device status=0\n");
    write_scratch(1, 0x00000051);

    write_scratch(1, 0x00000090);
    simputs("[SMBUS] ALL CHECKS PASSED\n");
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}
