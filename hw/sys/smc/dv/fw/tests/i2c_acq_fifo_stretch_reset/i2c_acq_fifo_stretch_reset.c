/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief I2C Target ACQ FIFO Stretch Release Test
 *
 * Verifies that an I2C target whose ACQ FIFO is full stretches SCL, that an
 * ACQ FIFO reset releases the stretch and empties the FIFO in hardware rather
 * than through the driver's software drain, and that after recovery from the
 * discarded write tail the target receives a new write correctly. I2C_1 is the
 * controller and I2C_0 the target.
 *
 * Firmware cannot observe the stretch, which is a duration on SCL. It parks at
 * two handshake markers, one while the FIFO is full and one right after the
 * ACQ reset, and the cocotb sequence samples the target's SCL drive in each
 * window (see smc_fw_i2c_acq_fifo_stretch_reset_test_seq.py).
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define TARGET_IDX 0
#define CONTROLLER_IDX 1
#define TARGET_ADDR 0x10
#define LONG_WRITE_LEN 70
#define VERIFY_WRITE_LEN 4

/* Poll bounds are given in simulated time and converted to loop iterations.
 * POLL_NS_PER_ITER is the cost of one poll iteration that does a single MMIO
 * read; a faster core clock shortens every bound by the same factor. The bus
 * runs at standard mode. */
#define POLL_NS_PER_ITER 430u
#define POLL_ITERS_FOR_NS(ns) (((ns) / POLL_NS_PER_ITER) + 1u)

/* General bound for controller and target state changes. */
#define POLL_TIMEOUT POLL_ITERS_FOR_NS(5000000u)
/* Must outlast filling the ACQ FIFO from the bus at standard mode, which takes
 * longer than POLL_TIMEOUT. */
#define ACQ_FILL_TIMEOUT POLL_ITERS_FOR_NS(20000000u)
/* A few SCL periods. A target still busy after this is receiving the discarded
 * write tail and is force-disabled instead of waited on. */
#define TARGET_IDLE_PROBE POLL_ITERS_FOR_NS(110000u)
/* Must outlast the testbench's marker poll and SCL sampling window. */
#define TB_ACK_BOUND POLL_ITERS_FOR_NS(5000000u)

/* Testbench handshake markers and acknowledge value. The acknowledge and the
 * observation payload use scratch registers that the console stream and the
 * error count leave free. */
#define SCR_STRETCH_OBS 0x00000031u
#define SCR_RELEASE_OBS 0x00000032u
#define SCR_TB_ACK 0x0000C10Au

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

/* The testbench derives its minimum stretch duration from the programmed
 * clock-low time, so it is read back from the DUT instead of copied here. */
static uint32_t get_timing_tlow(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__TIMING0_t timing0 = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR(0) -
                                                    SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    return timing0.f.TLOW;
}

/* Publish a marker and wait for the testbench to acknowledge it, so the
 * testbench can sample SCL while the DUT holds the state under test. A missing
 * acknowledge fails the phase instead of running past the observation window. */
static int tb_sync(uint32_t marker) {
    write_scratch(4, 0);
    write_scratch(1, marker);

    for (uint32_t i = 0; i < TB_ACK_BOUND; i++) {
        if (read_scratch(4) == SCR_TB_ACK) {
            return I2C_OK;
        }
    }

    simputshex32("  ERROR: sequence ACK timed out, marker=", marker);
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

/* Wait until the target reports that its ACQ FIFO has no room left. The
 * target's own full flag is the gate, not a level threshold copied from the
 * RTL, so the check follows any change of FIFO depth or margin. The level is
 * only reported. */
static int wait_for_acq_stretch(uint32_t idx, uint32_t *acqlvl_out) {
    uint32_t acqlvl = 0;

    for (uint32_t i = 0; i < ACQ_FILL_TIMEOUT; i++) {
        i2c__STATUS_t status = get_i2c_status(idx);

        acqlvl = get_acq_level(idx);
        if (status.f.ACQFULL) {
            simputshex32("  Target ACQ reached stretch threshold, acqlvl=", acqlvl);
            simputs("\n");
            *acqlvl_out = acqlvl;
            return I2C_OK;
        }
    }

    /* Report the sample that timed out, not a later re-read. */
    simputshex32("  ERROR: Timed out waiting for target ACQ stretch, last acqlvl=", acqlvl);
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

static int wait_for_acq_empty(uint32_t idx) {
    uint32_t acqlvl = 0;
    i2c__STATUS_t status;

    status.w = 0;
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        status = get_i2c_status(idx);
        acqlvl = get_acq_level(idx);

        if (status.f.ACQEMPTY && acqlvl == 0) {
            return I2C_OK;
        }
    }

    simputshex32("  ERROR: Timed out waiting for target ACQ empty, last acqlvl=", acqlvl);
    simputshex32(" last status=", status.w);
    simputs("\n");
    return I2C_ERROR_TIMEOUT;
}

static int wait_for_target_idle(uint32_t idx) {
    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        if (i2c_target_is_idle(idx)) {
            return I2C_OK;
        }
    }

    simputshex32("  ERROR: Timed out waiting for target idle, status=", get_i2c_status(idx).w);
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
    uint32_t events = 0xFFFFFFFFu;

    i2c_clear_controller_events(idx, 0xFFFFFFFF);

    for (uint32_t i = 0; i < POLL_TIMEOUT; i++) {
        events = i2c_get_controller_events(idx);

        if (events == 0) {
            return I2C_OK;
        }
    }

    simputshex32("  ERROR: Timed out clearing controller events, last events=", events);
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
                                             .clock_period_nanos = 5,
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

static int send_long_write_until_target_stretches(uint32_t *acqlvl_out) {
    uint8_t long_data[LONG_WRITE_LEN];

    for (uint32_t i = 0; i < LONG_WRITE_LEN; i++) {
        long_data[i] = (uint8_t)(0x40u + i);
    }

    simputs("  Controller sending long write to fill target ACQ FIFO...\n");
    int ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, long_data,
                                                        LONG_WRITE_LEN);
    if (ret != I2C_OK) {
        /* The later level check is graded against the bytes enqueued, so a
         * failed enqueue ends the test. */
        simputshex32("  ERROR: Long write enqueue failed, ret=", (uint32_t)ret);
        simputs("\n");
        return ret;
    }

    return wait_for_acq_stretch(TARGET_IDX, acqlvl_out);
}

/* Give the testbench a window to sample SCL, with the values it needs to
 * interpret what it sees. */
static int publish_stretch_observation(uint32_t acqlvl) {
    write_scratch(5, acqlvl);
    write_scratch(6, get_timing_tlow(CONTROLLER_IDX));
    write_scratch(7, get_i2c_status(TARGET_IDX).w);
    return tb_sync(SCR_STRETCH_OBS);
}

static int publish_release_observation(uint32_t lvl_before, uint32_t lvl_after) {
    write_scratch(5, lvl_before);
    write_scratch(6, lvl_after);
    write_scratch(7, get_i2c_status(TARGET_IDX).w);
    return tb_sync(SCR_RELEASE_OBS);
}

static int release_stretch_and_discard_long_write_tail(uint32_t acqlvl_at_stretch) {
    int ret;

    /* Release the stretch with an ACQ FIFO reset, then recover from the
     * interrupted long write: disable the controller, return the target to
     * idle, and reinitialize both. */

    /* Window 1: the target is out of room and holds SCL. The testbench requires
     * a continuous SCL pull longer than several programmed clock-low phases,
     * which tells a stretch apart from an ordinary clock-low phase. */
    ret = publish_stretch_observation(acqlvl_at_stretch);
    if (ret != I2C_OK) {
        return ret;
    }

    simputs("  ACQ reset (stretch release) then controller disable...\n");
    /* i2c_reset_fifos() drains the FIFO in software when the hardware reset
     * leaves entries behind, so the level after the call alone cannot show
     * that the hardware emptied it. The driver's drain flag and count tell the
     * two apart. */
    {
        i2c__STATUS_t status_before = get_i2c_status(TARGET_IDX);
        uint32_t lvl_before = get_acq_level(TARGET_IDX);
        uint32_t lvl_after;

        /* Before the reset the target must still report a full FIFO, and the
         * level must be consistent with the write enqueued: at most the payload
         * plus the address and header entries. */
        if (!status_before.f.ACQFULL || lvl_before == 0u ||
            lvl_before > (uint32_t)(LONG_WRITE_LEN + 2)) {
            simputshex32("  ERROR: ACQ not full-and-consistent before reset, acqlvl=", lvl_before);
            simputshex32(" status=", status_before.w);
            simputs("\n");
            return I2C_ERROR;
        }

        /* The driver's software repair is checked below instead of failing
         * inside the driver, so its fail-closed gate is opened for this call
         * only. */
        g_i2c_reset_repair_allowed = 1;
        i2c_reset_fifos(TARGET_IDX, false, false, false, true);
        g_i2c_reset_repair_allowed = 0;
        lvl_after = get_acq_level(TARGET_IDX);
        simputshex32("  ACQ reset: level ", lvl_before);
        simputshex32(" -> ", lvl_after);
        simputs(g_i2c_acq_reset_needed_drain ? " (helper had to drain)\n" : " (ACQRST alone)\n");
        if (lvl_after != 0u) {
            simputs("  ERROR: ACQ FIFO not empty after ACQRST\n");
            return I2C_ERROR;
        }
        /* The controller resumes the long write as soon as the stretch is
         * released, so a few entries can arrive before firmware reads the level
         * back and the driver drains them. The drain may remove at most a
         * quarter of the pre-reset level; a reset that did nothing leaves the
         * drain to remove all of it. */
        if (g_i2c_acq_reset_needed_drain && (g_i2c_acq_reset_drained * 4u) > lvl_before) {
            simputs("  ERROR: ACQRST did not empty the FIFO; the empty level above was\n");
            simputs("         produced by the driver's manual drain, not by the reset\n");
            simputshex32("         entries drained by hand=", g_i2c_acq_reset_drained);
            simputshex32(" of pre-reset level ", lvl_before);
            simputs("\n");
            return I2C_ERROR;
        }
        if (g_i2c_acq_reset_needed_drain) {
            /* Not a failure: entries that arrived after the release. Logged so
             * a drift toward the bound is visible. */
            simputshex32("  ACQRST emptied the FIFO; post-release refill=",
                         g_i2c_acq_reset_drained);
            simputshex32(" of ", lvl_before);
            simputs("\n");
        }

        /* Window 2: right after the reset and before the controller is
         * disabled, the testbench requires the SCL pull to be absent. Window 1
         * shows the probe can see a pull and window 2 that it can see none, so
         * neither passes on a stuck net. Bytes sent during this window are
         * discarded by the recovery below. */
        ret = publish_release_observation(lvl_before, lvl_after);
        if (ret != I2C_OK) {
            return ret;
        }
    }
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
        simputshex32("  ERROR: Verification length mismatch, got ", received_len);
        simputs("\n");
        return I2C_ERROR;
    }

    for (uint32_t i = 0; i < VERIFY_WRITE_LEN; i++) {
        if (received[i] != expected[i]) {
            simputshex32("  ERROR: Verification data mismatch at index ", i);
            simputshex32(", got ", received[i]);
            simputshex32(", expected ", expected[i]);
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
    uint32_t acqlvl_at_stretch = 0;

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
    ret = send_long_write_until_target_stretches(&acqlvl_at_stretch);
    if (ret != I2C_OK) {
        write_scratch(0, 0xBAD00020);
        test_fail(0);
    }

    write_scratch(1, 0x00000030);
    ret = release_stretch_and_discard_long_write_tail(acqlvl_at_stretch);
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
}
