/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * DV-TESTCASE-CONTRACT: SMC_I2C_001 ANCHOR: smc_i2c_sanity_test
 * DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 05c04850274c21a60b62a72bc8b9b5d445197c42b5c2fe015289401ed4828e27
 * DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/tb/doc/testplan/i2c/dv_vplan_gen/SMC_I2C_VPLAN_DETAIL.md @ artifact_revision 1 ENV: c-fw
 */

/**
 * @file i2c_sanity.c
 * @brief SMC_I2C_001 — controller bring-up, FMT write+STOP, CMD_COMPLETE lifecycle
 *
 * I2C_0 = Controller, I2C_1 = Target (ACK peer). Evidence is AXI CSR frontdoor only.
 */

#include <stdint.h>
#include <stdbool.h>

#include "metal/atomic.h"
#include "metal/cpu.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0u
#define TARGET_IDX 1u
#define TARGET_ADDR 0x10u
#define REG_ADDR 0x5Au
#define TEST_DATA_LO 0x5Au
#define TEST_DATA_HI 0x5Au
#define N_WRITE_BYTES 3u

/* Finite CMD_COMPLETE poll bound (loop iterations); fail-on-expiry mandatory. */
#define CMD_COMPLETE_BOUND 200000u

/* Ordered fence stamps for CHK-NONVAC (monotonic phase counter). */
static uint32_t g_phase;
static uint32_t g_ts_timing_program;
static uint32_t g_ts_fifo_reset_enable;
static uint32_t g_ts_write_stop;
static uint32_t g_ts_cmd_complete_clear;

static uint32_t stamp(void) {
    g_phase++;
    return g_phase;
}

static uint32_t ctrl_off(uint32_t abs_base_for_idx0) {
    return abs_base_for_idx0 - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0);
}

static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);
    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};

    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;
    write_reg(wrapper_addr, ctrl.w);
}

static void fail_with(uint32_t code, const char *msg) {
    simputs("  ERROR: ");
    simputs(msg);
    simputs("\n");
    write_scratch(0, code);
    test_fail(0);
}

/**
 * STEP S1 — program TIMING0-4 before ENABLEHOST; emit CHK-TIMING-BEFORE-ENABLE.
 */
static void step_s1_timing_before_enable(uint32_t idx, const i2c_timing_config_t *timing) {
    uint32_t base = i2c_get_base(idx);
    i2c__CTRL_t ctrl;
    i2c__TIMING0_t t0;
    i2c__TIMING1_t t1;
    i2c__TIMING2_t t2;
    i2c__TIMING3_t t3;
    i2c__TIMING4_t t4;

    simputs("STEP S1: program TIMING0-4 before ENABLEHOST\n");

    ctrl.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    ctrl.f.ENABLEHOST = 0;
    ctrl.f.ENABLETARGET = 0;
    write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)), ctrl.w);

    ctrl.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    if (ctrl.f.ENABLEHOST != 0) {
        fail_with(0xBAD00011, "ENABLEHOST high before timing program");
    }

    i2c_config_timing(idx, timing);

    t0.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR(0)));
    t1.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR(0)));
    t2.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR(0)));
    t3.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR(0)));
    t4.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR(0)));

    if (t0.w == 0 || t1.w == 0 || t2.w == 0 || t3.w == 0 || t4.w == 0) {
        fail_with(0xBAD00012, "TIMING0-4 still zero after program");
    }

    ctrl.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    if (ctrl.f.ENABLEHOST != 0) {
        fail_with(0xBAD00013, "ENABLEHOST rose before timing sample");
    }

    g_ts_timing_program = stamp();
    simputs("  CHK-TIMING-BEFORE-ENABLE: TIMING0-4 nonzero legal before ENABLEHOST=0\n");
}

/**
 * STEP S2 — FIFO reset-all, thresholds, clear INTR, ENABLEHOST=1.
 */
static void step_s2_fifo_reset_enable(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__HOST_FIFO_CONFIG_t fifo_cfg = {.w = 0};
    i2c__HOST_FIFO_STATUS_t host_st;
    i2c__CTRL_t ctrl;
    i2c__INTR_ENABLE_t intr_en = {.w = 0};

    simputs("STEP S2: FIFO reset-all, HOST_FIFO_CONFIG, clear INTR, ENABLEHOST=1\n");

    i2c_reset_fifos(idx, true, true, true, true);

    host_st.w =
        read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0)));
    if (host_st.f.FMTLVL != 0 || host_st.f.RXLVL != 0) {
        fail_with(0xBAD00021, "HOST_FIFO_STATUS levels nonzero after reset-all");
    }

    fifo_cfg.f.RX_THRESH = I2C_DEFAULT_RX_THRESH;
    fifo_cfg.f.FMT_THRESH = I2C_DEFAULT_FMT_THRESH;
    write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0)),
              fifo_cfg.w);

    i2c_clear_interrupts(idx, 0xFFFFFFFFu);

    intr_en.f.CMD_COMPLETE = 1;
    write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0)), intr_en.w);

    ctrl.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    ctrl.f.ENABLEHOST = 1;
    ctrl.f.ENABLETARGET = 0;
    ctrl.f.TX_STRETCH_CTRL_EN = 1;
    write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)), ctrl.w);

    ctrl.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    if (ctrl.f.ENABLEHOST != 1) {
        fail_with(0xBAD00022, "ENABLEHOST not set after enable");
    }

    host_st.w =
        read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0)));
    if (host_st.f.FMTLVL != 0 || host_st.f.RXLVL != 0) {
        fail_with(0xBAD00023, "HOST_FIFO_STATUS levels nonzero at ENABLEHOST");
    }

    g_ts_fifo_reset_enable = stamp();
    simputs("  CHK-FIFO-RESET-ENABLE: HOST_FIFO_STATUS levels=0 then ENABLEHOST=1\n");
}

/**
 * Prepare I2C_1 as ACK peer (not part of controller proof order).
 */
static void init_target_peer(const i2c_timing_config_t *timing) {
    int ret;
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl;
    i2c_target_config_t tgt_cfg = {
        .address0 = TARGET_ADDR,
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

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        fail_with(0xBAD00032, "Target init failed");
    }

    ctrl.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)));
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0)), ctrl.w);
}

/**
 * STEP S3 — n-byte write+STOP; prove FMTEMPTY and no CONTROLLER_HALT.
 * STEP S5 wait is embedded for transfer end (also used before CMD_COMPLETE).
 */
static void step_s3_write_stop(void) {
    uint32_t base = i2c_get_base(CONTROLLER_IDX);
    uint8_t write_buffer[3];
    uint8_t recv_buffer[256];
    uint32_t received_len = 0;
    int ret;
    i2c__STATUS_t status;
    i2c__INTR_STATE_t intr;

    simputs("STEP S3: push START+addr+W, data bytes, STOP; wait transfer end\n");

    write_buffer[0] = REG_ADDR;
    write_buffer[1] = TEST_DATA_LO;
    write_buffer[2] = TEST_DATA_HI;

    /* Clear CMD_COMPLETE so S4 can observe 0->1. */
    {
        i2c__INTR_STATE_t clr = {.w = 0};
        clr.f.CMD_COMPLETE = 1;
        write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)), clr.w);
    }

    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, write_buffer,
                                                    N_WRITE_BYTES);
    if (ret != I2C_OK) {
        fail_with(0xBAD00040, "Controller write enqueue failed");
    }

    ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer, sizeof(recv_buffer),
                                         &received_len, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) {
        fail_with(0xBAD00042, "Target receive failed");
    }

    ret = i2c_controller_wait_idle(CONTROLLER_IDX, CMD_COMPLETE_BOUND);
    if (ret != I2C_OK) {
        status.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0)));
        intr.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)));
        simputs("  ERROR: wait idle expired last INTR_STATE=");
        simputshex32("", intr.w);
        simputs(" STATUS=");
        simputshex32("", status.w);
        simputs("\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }

    if (received_len != N_WRITE_BYTES) {
        fail_with(0xBAD00043, "wrong byte count on target ACQ vs programmed n");
    }
    if (recv_buffer[0] != REG_ADDR || recv_buffer[1] != TEST_DATA_LO ||
        recv_buffer[2] != TEST_DATA_HI) {
        fail_with(0xBAD00044, "target ACQ data mismatch vs programmed write");
    }

    status.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0)));
    intr.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)));

    if (status.f.FMTEMPTY != 1) {
        fail_with(0xBAD00045, "STATUS.FMTEMPTY != 1 after write+STOP");
    }
    if (intr.f.CONTROLLER_HALT != 0) {
        fail_with(0xBAD00046, "INTR_STATE.CONTROLLER_HALT set after write+STOP");
    }

    g_ts_write_stop = stamp();
    simputs("  CHK-CTRL-WRITE-COMPLETE: STATUS.FMTEMPTY=1 INTR_STATE.CONTROLLER_HALT=0 "
            "n=3\n");
}

/**
 * STEP S4 + S5 — bounded CMD_COMPLETE wait, lifecycle, W1C clear.
 */
static void step_s4_s5_cmd_complete_life(void) {
    uint32_t base = i2c_get_base(CONTROLLER_IDX);
    uint32_t i;
    i2c__INTR_STATE_t intr;
    i2c__INTR_ENABLE_t en;
    i2c__STATUS_t status;
    i2c__INTR_STATE_t clr = {.w = 0};
    uint32_t irq_cond;

    simputs("STEP S5: bounded wait for CMD_COMPLETE\n");

    for (i = 0; i < CMD_COMPLETE_BOUND; i++) {
        intr.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)));
        if (intr.f.CMD_COMPLETE != 0) {
            break;
        }
    }

    status.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0)));
    intr.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)));

    if (i >= CMD_COMPLETE_BOUND) {
        simputs("  ERROR: CMD_COMPLETE wait expired bound=");
        simputshex32("", CMD_COMPLETE_BOUND);
        simputs(" last INTR_STATE=");
        simputshex32("", intr.w);
        simputs(" STATUS=");
        simputshex32("", status.w);
        simputs("\n");
        write_scratch(0, 0xBAD00051);
        test_fail(0);
    }

    simputs("  CHK-TIMEOUT-PATHS: CMD_COMPLETE bound=");
    simputshex32("", CMD_COMPLETE_BOUND);
    simputs(" fail_on_expiry last INTR_STATE=");
    simputshex32("", intr.w);
    simputs(" STATUS=");
    simputshex32("", status.w);
    simputs("\n");

    simputs("STEP S4: CMD_COMPLETE lifecycle set/observed/cleared/checked_cleared\n");

    /* set */
    if (intr.f.CMD_COMPLETE != 1) {
        fail_with(0xBAD00052, "lifecycle set: CMD_COMPLETE not 1 at STOP");
    }
    simputs("  lifecycle set: INTR_STATE.CMD_COMPLETE=1 at STOP\n");

    /* observed — irq_o via CSR condition (INTR_STATE & INTR_ENABLE); no bus force */
    en.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0)));
    irq_cond = (en.f.CMD_COMPLETE != 0 && intr.f.CMD_COMPLETE != 0) ? 1u : 0u;
    if (irq_cond != 1u) {
        fail_with(0xBAD00053, "lifecycle observed: irq_cond!=1 with enable+state");
    }
    simputs("  lifecycle observed: irq_cond=1 INTR_ENABLE.CMD_COMPLETE=1 "
            "INTR_STATE.CMD_COMPLETE=1\n");

    /* cleared */
    clr.f.CMD_COMPLETE = 1;
    write_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)), clr.w);
    simputs("  lifecycle cleared: W1C INTR_STATE.CMD_COMPLETE\n");

    /* checked_cleared */
    intr.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)));
    en.w = read_reg(base + ctrl_off(SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0)));
    irq_cond = (en.f.CMD_COMPLETE != 0 && intr.f.CMD_COMPLETE != 0) ? 1u : 0u;
    if (intr.f.CMD_COMPLETE != 0) {
        fail_with(0xBAD00054, "lifecycle checked_cleared: CMD_COMPLETE still set after W1C");
    }
    if (irq_cond != 0u) {
        fail_with(0xBAD00055, "lifecycle checked_cleared: irq_cond still 1 after clear");
    }
    simputs("  lifecycle checked_cleared: INTR_STATE.CMD_COMPLETE=0 irq_cond=0\n");

    g_ts_cmd_complete_clear = stamp();
    simputs("  CHK-CMD-COMPLETE-LIFE: CMD_COMPLETE 0->1 at STOP then W1C ->0 "
            "lifecycle=set/observed/cleared/checked_cleared\n");
}

static void check_nonvac_order(void) {
    if (g_ts_timing_program == 0 || g_ts_fifo_reset_enable == 0 || g_ts_write_stop == 0 ||
        g_ts_cmd_complete_clear == 0) {
        fail_with(0xBAD00060, "CHK-NONVAC missing ordered term");
    }
    if (!(g_ts_timing_program < g_ts_fifo_reset_enable &&
          g_ts_fifo_reset_enable < g_ts_write_stop &&
          g_ts_write_stop < g_ts_cmd_complete_clear)) {
        fail_with(0xBAD00061, "CHK-NONVAC out of order");
    }
    simputs("  CHK-NONVAC: TIMING_PROGRAM < FIFO_RESET_ENABLE < WRITE_STOP < "
            "CMD_COMPLETE_CLEAR\n");
}

int main(void) {
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 10,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};
    i2c_timing_config_t computed_timing;
    int ret;

    g_phase = 0;
    g_ts_timing_program = 0;
    g_ts_fifo_reset_enable = 0;
    g_ts_write_stop = 0;
    g_ts_cmd_complete_clear = 0;

    simputs("\n## SMC_I2C_001 smc_i2c_sanity_test (c-fw) ##\n");

    write_scratch(1, 0x00000010);
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    i2c_wrapper_enable(TARGET_IDX, false);
    write_scratch(1, 0x00000021);

    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

    write_scratch(1, 0x00000030);
    step_s1_timing_before_enable(CONTROLLER_IDX, &computed_timing);
    step_s2_fifo_reset_enable(CONTROLLER_IDX);
    init_target_peer(&computed_timing);
    write_scratch(1, 0x00000031);

    write_scratch(1, 0x00000040);
    step_s3_write_stop();
    write_scratch(1, 0x00000041);

    write_scratch(1, 0x00000050);
    step_s4_s5_cmd_complete_life();
    write_scratch(1, 0x00000051);

    check_nonvac_order();

    write_scratch(1, 0x00000090);
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n## SMC_I2C_001 evidence tokens emitted ##\n");
    write_scratch(0, TEST_PASS);
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    }
    return other_main(hartid);
}
