/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file main.c
 * @brief I2C target TX stretch timeout recovery test
 *
 * I2C_1 acts as controller and I2C_0 acts as target. The controller first
 * issues a READ while the target TX FIFO is empty, causing automatic TX clock
 * stretch until the controller times out.
 * Firmware then disables the target to release the stretch, disables the
 * controller to exercise the automatic STOP recovery path, reinitializes both
 * sides, and verifies that a following 16-byte WRITE is received correctly.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define TARGET_IDX 0
#define CONTROLLER_IDX 1
#define TARGET_ADDR 0x10
#define VERIFY_WRITE_LEN 16
#define READ_STRETCH_TIMEOUT_CYCLES 2000
#define READ_STRETCH_SETTLE_CYCLES 256

/* Poll bound for the stretch timeout report. Generous against the ~100 us the
 * bus needs to reach the stretch, but finite so a stretch that never happens
 * fails here with a diagnostic instead of running into the TB's timeout. */
#define READ_STRETCH_POLL_BOUND 20000u
#define POLL_TIMEOUT 10000

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

static i2c__STATUS_t get_i2c_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__STATUS_t status = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    return status;
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

/* Last INTR_STATE sampled by clear_controller_events_and_wait() before it
 * cleared: the sample that carries the property under test has to be taken
 * before the blanket 0xFFFFFFFF clear destroys it. Callers that provoke a
 * timeout read this. */
static uint32_t g_last_intr_state_before_clear;

static int clear_controller_events_and_wait(uint32_t idx) {
    g_last_intr_state_before_clear = i2c_get_interrupt_state(idx);
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

static int clear_target_events_and_wait(uint32_t idx) {
    i2c_clear_target_events(idx, 0xFFFFFFFF);

    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        uint32_t events = i2c_get_target_events(idx);

        if (events == 0) {
            return I2C_OK;
        }
    }

    simputs("  ERROR: Timed out clearing target events, events=0x");
    simputshex32("", i2c_get_target_events(idx));
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
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
                                              .timeout_cycles = READ_STRETCH_TIMEOUT_CYCLES};

    int ret = i2c_controller_init(CONTROLLER_IDX, &controller_cfg);
    if (ret != I2C_OK) {
        return ret;
    }

    i2c_config_timeout(CONTROLLER_IDX, READ_STRETCH_TIMEOUT_CYCLES, true, true);

    /* Enable the STRETCH_TIMEOUT interrupt for the property under test.
     *
     * INTR_STATE.STRETCH_TIMEOUT latches whether or not the interrupt is
     * enabled (INTR_ENABLE masks irq_o only), so the status read below does
     * not depend on this. Enabling it as well keeps the interrupt line as a
     * second, independent observation of the same event. */
    i2c_enable_interrupts(CONTROLLER_IDX, I2C__INTR_ENABLE__STRETCH_TIMEOUT_bm);
    return I2C_OK;
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

    i2c_reset_fifos(TARGET_IDX, false, false, true, true);
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

static int wait_for_controller_fmt_space(uint32_t idx, uint32_t required_space) {
    uint32_t base = i2c_get_base(idx);

    write_scratch(1, 0x00000021);
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        i2c__HOST_FIFO_STATUS_t fifo_status = {
            .w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if ((64u - fifo_status.f.FMTLVL) >= required_space) {
            write_scratch(1, 0x00000022);
            return I2C_OK;
        }
    }

    simputs("  ERROR: Timed out waiting for controller FMT FIFO space\n");
    return I2C_ERROR_TIMEOUT;
}

static int enqueue_controller_read_one_byte(void) {
    uint32_t base = i2c_get_base(CONTROLLER_IDX);
    int ret = wait_for_controller_fmt_space(CONTROLLER_IDX, 2);
    if (ret != I2C_OK) {
        return ret;
    }

    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = (TARGET_ADDR << 1) | 0x1;
    fdata.f.START = 1;
    fdata.f.READB = 0;
    write_scratch(1, 0x00000023);
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    fdata.w = 0;
    fdata.f.FBYTE = 1;
    fdata.f.READB = 1;
    fdata.f.RCONT = 0;
    fdata.f.STOP = 1;
    write_scratch(1, 0x00000024);
    write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
              fdata.w);

    write_scratch(1, 0x00000025);
    return I2C_OK;
}

static int trigger_read_timeout(void) {
    int ret;

    simputs("  Controller issuing READ while target TX FIFO is empty...\n");
    ret = enqueue_controller_read_one_byte();
    if (ret != I2C_OK) {
        return ret;
    }

    write_scratch(1, 0x00000026);

    /* Wait for the stretch timeout to be reported, rather than spinning a fixed
     * count and assuming it happened.
     *
     * The fixed READ_STRETCH_SETTLE_CYCLES window was 256 iterations ~= 50.6 us,
     * against the ~98.7 us this test's own programmed timing needs just to get
     * START + address + ACK onto the bus -- so recovery began before the target
     * had started stretching, and the stretch under test never occurred. Nothing
     * measured it either way, so the test passed on a bus that stayed idle.
     *
     * Polling the status bit makes the wait self-timing and turns the property
     * into something that can fail: with the enqueue above removed, no timeout
     * is ever reported and this returns an error. */
    {
        uint32_t polls = 0;
        i2c__INTR_STATE_t intr = {.w = 0};

        while (polls < READ_STRETCH_POLL_BOUND) {
            intr.w = i2c_get_interrupt_state(CONTROLLER_IDX);
            if (intr.f.STRETCH_TIMEOUT) {
                break;
            }
            polls++;
        }

        if (!intr.f.STRETCH_TIMEOUT) {
            simputs("  ERROR: STRETCH_TIMEOUT never reported after ");
            simputshex32("", polls);
            simputs(" polls; INTR_STATE=");
            simputshex32("", intr.w);
            simputs("\n");
            return I2C_ERROR_TIMEOUT;
        }

        simputs("  STRETCH_TIMEOUT observed after ");
        simputshex32("", polls);
        simputs(" polls, INTR_STATE=");
        simputshex32("", intr.w);
        simputs("\n");
    }

    write_scratch(1, 0x00000027);
    simputs("  Controller READ stretch timeout observed; starting recovery\n");
    return I2C_OK;
}

static int recover_after_read_timeout(void) {
    int ret;

    simputs("  Disabling target to release TX stretch...\n");
    i2c_target_disable(TARGET_IDX);

    simputs("  Clearing target events after target disable...\n");
    ret = clear_target_events_and_wait(TARGET_IDX);
    if (ret != I2C_OK) {
        return ret;
    }

    simputs("  Disabling controller to request automatic STOP recovery...\n");
    i2c_controller_disable(CONTROLLER_IDX);

    simputs("  Waiting for controller idle after automatic STOP recovery...\n");
    ret = i2c_controller_wait_idle(CONTROLLER_IDX, POLL_TIMEOUT);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller did not become idle after disable recovery\n");
        return ret;
    }

    simputs("  Waiting for target idle after disable recovery...\n");
    ret = wait_for_target_idle(TARGET_IDX);
    if (ret != I2C_OK) {
        return ret;
    }

    simputs("  Clearing controller events and FIFOs after timeout recovery...\n");
    ret = clear_controller_events_and_wait(CONTROLLER_IDX);
    if (ret != I2C_OK) {
        return ret;
    }

    i2c_reset_fifos(CONTROLLER_IDX, true, true, false, false);
    i2c_reset_fifos(TARGET_IDX, false, false, true, true);

    simputs("  Reinitializing target after timeout recovery...\n");
    ret = init_target();
    if (ret != I2C_OK) {
        simputs("  ERROR: Target reinitialization failed\n");
        return ret;
    }

    simputs("  Reinitializing controller after timeout recovery...\n");
    ret = init_controller();
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller reinitialization failed\n");
        return ret;
    }

    return I2C_OK;
}

static int send_and_check_verify_write(void) {
    uint8_t expected[VERIFY_WRITE_LEN];
    uint8_t received[VERIFY_WRITE_LEN + 4] = {0};
    uint32_t received_len = 0;

    for (uint32_t i = 0; i < VERIFY_WRITE_LEN; i++) {
        expected[i] = (uint8_t)(0x80u + i);
    }

    simputs("  Controller sending 16-byte verification write...\n");
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
    simputs("############################################################\n");
    simputs("## I2C TX Stretch Timeout Recovery Test                  ##\n");
    simputs("############################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    ret = init_i2c_pair();
    if (ret != I2C_OK) {
        simputs("ERROR: I2C pair initialization failed\n");
        write_scratch(0, 0xBAD00010);
        test_fail(0);
    }

    write_scratch(1, 0x00000020);
    ret = trigger_read_timeout();
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00020);
        test_fail(0);
    }

    write_scratch(1, 0x00000030);
    ret = recover_after_read_timeout();
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

    write_scratch(1, 0xEBEDEBE5);
    simputs("\n");
    simputs("############################################################\n");
    simputs("## I2C TX Stretch Timeout Recovery Test PASSED           ##\n");
    simputs("############################################################\n");
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}
