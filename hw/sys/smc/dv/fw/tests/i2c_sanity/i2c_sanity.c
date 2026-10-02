/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* DV-TESTCASE-CONTRACT: SMC_I2C_001 ANCHOR: smc_i2c_sanity_test ENV: c-fw */

/**
 * @file i2c_sanity.c
 * @brief SMC_I2C_001 - controller bring-up, write with STOP, command-complete lifecycle
 *
 * Checks I2C controller bring-up and a basic write, with I2C_0 as controller
 * and I2C_1 as the acknowledging target: timing readback before enable, a
 * hardware FIFO reset, an in-order three-byte write, the command-complete
 * interrupt from set through delivery to clear, and a NACK that halts the
 * controller. Evidence comes from register reads only, and every check
 * prints a CHK-* token.
 *
 * Every wait is bounded to expire inside the testbench time budget, so a
 * hang ends with this firmware's failure code, not a harness timeout.
 */

#include <stdint.h>
#include <stdbool.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "tt_smc_interrupts.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0u
#define TARGET_IDX 1u
#define TARGET_ADDR 0x10u

/* No target answers this address, so the address phase is NACKed and the
 * controller halts. S6 uses it as the positive control for CONTROLLER_HALT. */
#define UNUSED_ADDR 0x55u

/* Distinct payload bytes, so the byte-for-byte compare in S3 can tell a
 * reordering or a duplication from a correct transfer. */
#define REG_ADDR 0x5Au
#define TEST_DATA_LO 0xA3u
#define TEST_DATA_HI 0x1Cu
#define N_WRITE_BYTES 3u

/* Entries pushed into the FMT FIFO by the S2 reset proof. Any small number
 * below CONTROLLER_TX_FIFO_DEPTH works; the point is that the level is observed
 * non-zero before the reset is applied. */
#define FMT_FILL_ENTRIES 3u

/* Bounded-wait budget, in poll iterations. It must cover the longest
 * legitimate wait, the 5-byte standard-mode transfer (about 3300 iterations at
 * the fastest core clock), with margin, and still expire inside the testbench
 * time budget; I2C_TIMEOUT_DEFAULT is too long for that. */
#define I2C_WAIT_BOUND 12000u

/* Deliberate-expiry control (S5). Long enough that a genuinely pending
 * CMD_COMPLETE would be seen, short enough to cost ~0.1-0.2 ms. */
#define IDLE_HOLD_BOUND 200u

/* I2C interrupt to PLIC observation window. The interrupt reaches the PLIC
 * within a few cycles and each poll is a CSR read, so this is generous. */
#define PLIC_PENDING_BOUND 200u

/* PLIC source of the controller instance. Keep in step with CONTROLLER_IDX. */
#define CONTROLLER_PLIC_ID ((uint32_t)I2C_0_INTERRUPT_ID)

/* Measured values carried between steps for the evidence tokens. */
static uint32_t g_plic_pending_before;
static uint32_t g_plic_pending_set;
static uint32_t g_plic_pending_after_clear;
static uint32_t g_cmd_complete_iters;
static uint32_t g_idle_hold_iters;
static uint32_t g_fmt_level_filled;
static uint32_t g_fmt_level_after_rst;

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
 * @brief PLIC pending bit for one interrupt source.
 *
 * The PLIC pending array is the first place outside the I2C block where irq_o
 * becomes visible to software, so it is the downstream observation the
 * CMD_COMPLETE lifecycle needs. Note the RISC-V PLIC gateway latches a pending
 * request until it is claimed: a 0 -> 1 transition is proof of delivery, but a
 * return to 0 after the interrupt source deasserts is not guaranteed without a
 * claim, so this testcase asserts only the rising edge and reports the rest.
 */
static uint32_t plic_pending_bit(uint32_t plic_id) {
    uint32_t word = read_reg(SMC_TOP_SMC_CLUSTER_PLIC_PENDING_BASE_ADDR(plic_id / 32u));

    return (word >> (plic_id % 32u)) & 1u;
}

static uint32_t i2c_rd(uint32_t base, uint32_t abs_base_for_idx0) {
    return read_reg(base + ctrl_off(abs_base_for_idx0));
}

static void i2c_wr(uint32_t base, uint32_t abs_base_for_idx0, uint32_t value) {
    write_reg(base + ctrl_off(abs_base_for_idx0), value);
}

/**
 * STEP S1 - program TIMING0-4 before ENABLEHOST; emit CHK-TIMING-BEFORE-ENABLE.
 *
 * Requires ENABLEHOST to stay 0 across the timing program, and every timing
 * field to read back the value i2c_compute_timing_from_physical() computed.
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

    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    ctrl.f.ENABLEHOST = 0;
    ctrl.f.ENABLETARGET = 0;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0), ctrl.w);

    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    if (ctrl.f.ENABLEHOST != 0) {
        fail_with(0xBAD00011, "ENABLEHOST high before timing program");
    }

    i2c_config_timing(idx, timing);

    t0.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR(0));
    t1.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR(0));
    t2.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR(0));
    t3.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR(0));
    t4.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR(0));

    /* Truncate each computed value to its field width, as i2c_config_timing()
     * does. */
    if (t0.f.THIGH != (timing->thigh & 0x1FFFu) || t0.f.TLOW != (timing->tlow & 0x1FFFu) ||
        t1.f.T_R != (timing->t_r & 0x3FFu) || t1.f.T_F != (timing->t_f & 0x1FFu) ||
        t2.f.TSU_STA != (timing->tsu_sta & 0x1FFFu) ||
        t2.f.THD_STA != (timing->thd_sta & 0x1FFFu) || t3.f.TSU_DAT != (timing->tsu_dat & 0x1FFu) ||
        t3.f.THD_DAT != (timing->thd_dat & 0x1FFFu) ||
        t4.f.TSU_STO != (timing->tsu_sto & 0x1FFFu) || t4.f.T_BUF != (timing->t_buf & 0x1FFFu)) {
        simputs("  ERROR: TIMING readback != computed. read t0=");
        simputshex32("", t0.w);
        simputs(" t1=");
        simputshex32("", t1.w);
        simputs(" t2=");
        simputshex32("", t2.w);
        simputs(" t3=");
        simputshex32("", t3.w);
        simputs(" t4=");
        simputshex32("", t4.w);
        simputs(" computed thigh=");
        simputshex32("", timing->thigh);
        simputs(" tlow=");
        simputshex32("", timing->tlow);
        simputs(" t_r=");
        simputshex32("", timing->t_r);
        simputs(" t_f=");
        simputshex32("", timing->t_f);
        simputs("\n");
        write_scratch(0, 0xBAD00012);
        test_fail(0);
    }

    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    if (ctrl.f.ENABLEHOST != 0) {
        fail_with(0xBAD00013, "ENABLEHOST rose before timing sample");
    }

    simputs("  CHK-TIMING-BEFORE-ENABLE: ENABLEHOST=0 across program; TIMING0-4 == computed t0=");
    simputshex32("", t0.w);
    simputs(" t1=");
    simputshex32("", t1.w);
    simputs(" t2=");
    simputshex32("", t2.w);
    simputs(" t3=");
    simputshex32("", t3.w);
    simputs(" t4=");
    simputshex32("", t4.w);
    simputs("\n");
}

/**
 * @brief Prove the hardware FMT reset empties a FIFO observed non-empty.
 *
 * Fills the FMT FIFO while the controller is disabled, so the FSM cannot pop
 * it, and requires the level to read back. Then resets the FIFO directly, not
 * through i2c_reset_fifos(), which repairs a reset that did not take, and
 * requires the level to be zero.
 */
static void prove_fmt_reset(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__HOST_FIFO_STATUS_t host_st;
    i2c__FIFO_CTRL_t fifo_ctrl = {.w = 0};
    i2c__STATUS_t status;
    i2c__FDATA_t fdata;
    i2c__CTRL_t ctrl;
    uint32_t i;

    /* The level is only stable while the FSM cannot pop the FIFO. */
    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    if (ctrl.f.ENABLEHOST != 0) {
        fail_with(0xBAD00028, "ENABLEHOST set before the FMT reset proof");
    }

    for (i = 0; i < FMT_FILL_ENTRIES; i++) {
        status.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0));
        if (status.f.FMTFULL != 0) {
            fail_with(0xBAD00027, "FMT FIFO full while filling for the reset proof");
        }
        fdata.w = 0;
        fdata.f.FBYTE = 0x11u * (i + 1u); /* payload is irrelevant; it is never sent */
        i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0), fdata.w);
    }

    host_st.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0));
    g_fmt_level_filled = host_st.f.FMTLVL;
    if (g_fmt_level_filled != FMT_FILL_ENTRIES) {
        simputs("  ERROR: FMT fill not observed, FMTLVL=");
        simputshex32("", g_fmt_level_filled);
        simputs(" expected=");
        simputshex32("", FMT_FILL_ENTRIES);
        simputs("\n");
        write_scratch(0, 0xBAD00024);
        test_fail(0);
    }

    fifo_ctrl.w = 0;
    fifo_ctrl.f.FMTRST = 1;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR(0), fifo_ctrl.w);

    host_st.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0));
    g_fmt_level_after_rst = host_st.f.FMTLVL;
    if (g_fmt_level_after_rst != 0) {
        simputs("  ERROR: FMTRST left entries behind, FMTLVL=");
        simputshex32("", g_fmt_level_after_rst);
        simputs(" was=");
        simputshex32("", g_fmt_level_filled);
        simputs("\n");
        write_scratch(0, 0xBAD00025);
        test_fail(0);
    }
}

/**
 * STEP S2 - prove the FMT reset, reset-all, thresholds, clear INTR, ENABLEHOST=1.
 */
static void step_s2_fifo_reset_enable(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__HOST_FIFO_CONFIG_t fifo_cfg = {.w = 0};
    i2c__HOST_FIFO_STATUS_t host_st;
    i2c__CTRL_t ctrl;
    i2c__INTR_ENABLE_t intr_en = {.w = 0};

    simputs("STEP S2: FMT reset proof, reset-all, HOST_FIFO_CONFIG, clear INTR, ENABLEHOST=1\n");

    prove_fmt_reset(idx);

    i2c_reset_fifos(idx, true, true, true, true);

    /* i2c_reset_fifos() repairs a reset that did not take and records it in
     * these flags; a repair means the hardware reset failed. */
    if (g_i2c_acq_reset_needed_drain != 0 || g_i2c_rx_reset_needed_drain != 0 ||
        g_i2c_fmt_reset_needed_retry != 0 || g_i2c_tx_reset_needed_retry != 0) {
        simputs("  ERROR: reset-all needed software repair acq=");
        simputshex32("", g_i2c_acq_reset_needed_drain);
        simputs(" rx=");
        simputshex32("", g_i2c_rx_reset_needed_drain);
        simputs(" fmt=");
        simputshex32("", g_i2c_fmt_reset_needed_retry);
        simputs(" tx=");
        simputshex32("", g_i2c_tx_reset_needed_retry);
        simputs("\n");
        write_scratch(0, 0xBAD00026);
        test_fail(0);
    }

    host_st.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0));
    if (host_st.f.FMTLVL != 0 || host_st.f.RXLVL != 0) {
        fail_with(0xBAD00021, "HOST_FIFO_STATUS levels nonzero after reset-all");
    }

    fifo_cfg.f.RX_THRESH = I2C_DEFAULT_RX_THRESH;
    fifo_cfg.f.FMT_THRESH = I2C_DEFAULT_FMT_THRESH;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0), fifo_cfg.w);

    i2c_clear_interrupts(idx, 0xFFFFFFFFu);
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0), 0xFu);

    /* CONTROLLER_HALT is enabled as well as CMD_COMPLETE so that a halt is
     * also visible on the interrupt line (INTR_ENABLE masks irq_o only; the
     * INTR_STATE bits themselves report regardless of the enable). S6 is the
     * positive control for the CONTROLLER_HALT == 0 term in S3. */
    intr_en.f.CMD_COMPLETE = 1;
    intr_en.f.CONTROLLER_HALT = 1;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0), intr_en.w);

    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    ctrl.f.ENABLEHOST = 1;
    ctrl.f.ENABLETARGET = 0;
    ctrl.f.TX_STRETCH_CTRL_EN = 1;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0), ctrl.w);

    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    if (ctrl.f.ENABLEHOST != 1) {
        fail_with(0xBAD00022, "ENABLEHOST not set after enable");
    }

    host_st.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0));
    if (host_st.f.FMTLVL != 0 || host_st.f.RXLVL != 0) {
        fail_with(0xBAD00023, "HOST_FIFO_STATUS levels nonzero at ENABLEHOST");
    }

    simputs("  CHK-FIFO-RESET-ENABLE: FMTLVL filled=");
    simputshex32("", g_fmt_level_filled);
    simputs(" after FMTRST=");
    simputshex32("", g_fmt_level_after_rst);
    simputs(" reset-all repair flags acq/rx/fmt/tx=");
    simputshex32("", g_i2c_acq_reset_needed_drain);
    simputshex32("/", g_i2c_rx_reset_needed_drain);
    simputshex32("/", g_i2c_fmt_reset_needed_retry);
    simputshex32("/", g_i2c_tx_reset_needed_retry);
    simputs(" then CTRL=");
    simputshex32("", ctrl.w);
    simputs("\n");
}

/**
 * Prepare I2C_1 as ACK peer (not part of controller proof order).
 */
static void init_target_peer(const i2c_timing_config_t *timing) {
    int ret;
    uint32_t base = i2c_get_base(TARGET_IDX);
    i2c__CTRL_t ctrl;
    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
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

    ctrl.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0));
    ctrl.f.ACQ_START_STOP_EN = 1;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0), ctrl.w);
}

/**
 * STEP S3 - n-byte write; prove the controller consumed the STOP-flagged entry.
 *
 * HOSTIDLE with an empty FMT FIFO proves the controller consumed every FDATA
 * entry, including the STOP-flagged one. The target side does not prove a
 * STOP: i2c_target_receive_transaction() returns once the header's byte count
 * has arrived, before the STOP entry is read.
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
        i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0), clr.w);
    }

    /* Baseline for the lifecycle "observed" leg: with every interrupt cleared
     * and the bus idle, nothing of this instance's should be pending at the
     * PLIC. Without this the later pending == 1 could be a stuck bit. */
    g_plic_pending_before = plic_pending_bit(CONTROLLER_PLIC_ID);
    if (g_plic_pending_before != 0u) {
        simputs("  ERROR: PLIC pending already set for this I2C before the transfer, id=");
        simputshex32("", CONTROLLER_PLIC_ID);
        simputs(" INTR_STATE=");
        simputshex32("", i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0)));
        simputs("\n");
        write_scratch(0, 0xBAD00047);
        test_fail(0);
    }

    ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, write_buffer,
                                                    N_WRITE_BYTES);
    if (ret != I2C_OK) {
        fail_with(0xBAD00040, "Controller write enqueue failed");
    }

    ret = i2c_target_receive_transaction(TARGET_IDX, recv_buffer, sizeof(recv_buffer),
                                         &received_len, I2C_WAIT_BOUND);
    if (ret != I2C_OK) {
        uint32_t tgt_base = i2c_get_base(TARGET_IDX);

        simputs("  ERROR: target receive failed ret=");
        simputshex32("", (uint32_t)ret);
        simputs(" received_len=");
        simputshex32("", received_len);
        simputs(" TARGET_FIFO_STATUS=");
        simputshex32("",
                     i2c_rd(tgt_base, SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0)));
        simputs("\n");
        write_scratch(0, 0xBAD00042);
        test_fail(0);
    }

    ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_WAIT_BOUND);
    if (ret != I2C_OK) {
        status.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0));
        intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
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
        simputs("  ERROR: target ACQ data mismatch, got=");
        simputshex32("", recv_buffer[0]);
        simputshex32("/", recv_buffer[1]);
        simputshex32("/", recv_buffer[2]);
        simputs(" expected=");
        simputshex32("", REG_ADDR);
        simputshex32("/", TEST_DATA_LO);
        simputshex32("/", TEST_DATA_HI);
        simputs("\n");
        write_scratch(0, 0xBAD00044);
        test_fail(0);
    }

    status.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0));
    intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));

    if (status.f.FMTEMPTY != 1) {
        fail_with(0xBAD00045, "STATUS.FMTEMPTY != 1 after write");
    }
    /* Read against S6, which demonstrates this bit can reach 1. */
    if (intr.f.CONTROLLER_HALT != 0) {
        fail_with(0xBAD00046, "INTR_STATE.CONTROLLER_HALT set after write");
    }

    simputs("  CHK-CTRL-WRITE-COMPLETE: controller consumed the STOP-flagged FDATA entry, STATUS=");
    simputshex32("", status.w);
    simputs(" INTR_STATE=");
    simputshex32("", intr.w);
    simputs(" received_len=");
    simputshex32("", received_len);
    simputs(" of n=");
    simputshex32("", N_WRITE_BYTES);
    simputs("\n");
}

/**
 * STEP S4 + S5 - bounded CMD_COMPLETE wait, lifecycle, W1C clear.
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

    for (i = 0; i < I2C_WAIT_BOUND; i++) {
        intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
        if (intr.f.CMD_COMPLETE != 0) {
            break;
        }
    }
    g_cmd_complete_iters = i;

    status.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0));
    intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));

    if (i >= I2C_WAIT_BOUND) {
        simputs("  ERROR: CMD_COMPLETE wait expired bound=");
        simputshex32("", I2C_WAIT_BOUND);
        simputs(" last INTR_STATE=");
        simputshex32("", intr.w);
        simputs(" STATUS=");
        simputshex32("", status.w);
        simputs("\n");
        write_scratch(0, 0xBAD00051);
        test_fail(0);
    }

    simputs("STEP S4: CMD_COMPLETE lifecycle set/observed/cleared/checked_cleared\n");

    /* set */
    if (intr.f.CMD_COMPLETE != 1) {
        fail_with(0xBAD00052, "lifecycle set: CMD_COMPLETE not 1 after transfer");
    }
    simputs("  lifecycle set: INTR_STATE.CMD_COMPLETE=1 after transfer\n");

    /* observed: the PLIC pending bit is the first software-visible point past
     * the I2C interrupt output. */
    for (i = 0; i < PLIC_PENDING_BOUND; i++) {
        g_plic_pending_set = plic_pending_bit(CONTROLLER_PLIC_ID);
        if (g_plic_pending_set != 0u) {
            break;
        }
    }
    if (g_plic_pending_set != 1u) {
        simputs("  ERROR: irq not delivered; PLIC pending still 0 after ");
        simputshex32("", PLIC_PENDING_BOUND);
        simputs(" polls, id=");
        simputshex32("", CONTROLLER_PLIC_ID);
        simputs(" INTR_STATE=");
        simputshex32("", intr.w);
        simputs(" INTR_ENABLE=");
        simputshex32("", i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0)));
        simputs("\n");
        write_scratch(0, 0xBAD00053);
        test_fail(0);
    }
    en.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0));
    simputs("  lifecycle observed: PLIC pending id=");
    simputshex32("", CONTROLLER_PLIC_ID);
    simputs(" before=");
    simputshex32("", g_plic_pending_before);
    simputs(" now=");
    simputshex32("", g_plic_pending_set);
    simputs(" after polls=");
    simputshex32("", i);
    simputs(" INTR_ENABLE=");
    simputshex32("", en.w);
    simputs("\n");

    /* cleared */
    clr.f.CMD_COMPLETE = 1;
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0), clr.w);
    simputs("  lifecycle cleared: W1C INTR_STATE.CMD_COMPLETE\n");

    /* checked_cleared */
    intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
    en.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0));
    irq_cond = (en.f.CMD_COMPLETE != 0 && intr.f.CMD_COMPLETE != 0) ? 1u : 0u;
    if (intr.f.CMD_COMPLETE != 0) {
        fail_with(0xBAD00054, "lifecycle checked_cleared: CMD_COMPLETE still set after W1C");
    }
    if (irq_cond != 0u) {
        fail_with(0xBAD00055, "lifecycle checked_cleared: irq_cond still 1 after clear");
    }
    /* The PLIC gateway latches a pending request until it is claimed, so this
     * value is reported, not asserted: a 1 here is the latch, not a stuck irq. */
    g_plic_pending_after_clear = plic_pending_bit(CONTROLLER_PLIC_ID);
    simputs("  lifecycle checked_cleared: INTR_STATE.CMD_COMPLETE=0 irq_cond=0 PLIC pending=");
    simputshex32("", g_plic_pending_after_clear);
    simputs(" (latched until claimed; reported, not asserted)\n");

    /* Deliberate-expiry control for the bounded-wait machinery.
     *
     * This wait is expected to expire: the bus is idle and CMD_COMPLETE was just
     * cleared, so it must stay 0 for the whole window. That runs the expiry leg
     * on every passing run, and a spurious CMD_COMPLETE while idle fails it. */
    for (i = 0; i < IDLE_HOLD_BOUND; i++) {
        intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
        if (intr.f.CMD_COMPLETE != 0) {
            break;
        }
    }
    g_idle_hold_iters = i;
    if (g_idle_hold_iters != IDLE_HOLD_BOUND) {
        simputs("  ERROR: CMD_COMPLETE re-asserted on an idle bus after ");
        simputshex32("", g_idle_hold_iters);
        simputs(" polls, INTR_STATE=");
        simputshex32("", intr.w);
        simputs("\n");
        write_scratch(0, 0xBAD00056);
        test_fail(0);
    }

    simputs("  CHK-TIMEOUT-PATHS: bound=");
    simputshex32("", I2C_WAIT_BOUND);
    simputs(" CMD_COMPLETE wait consumed=");
    simputshex32("", g_cmd_complete_iters);
    simputs(" iterations; expiry leg exercised: idle-hold wait ran to its bound=");
    simputshex32("", g_idle_hold_iters);
    simputs(" of ");
    simputshex32("", IDLE_HOLD_BOUND);
    simputs("\n");

    simputs("  CHK-CMD-COMPLETE-LIFE: CMD_COMPLETE 0->1 after transfer, PLIC pending 0->1, "
            "then W1C ->0 lifecycle=set/observed/cleared/checked_cleared\n");
}

/**
 * STEP S6 - positive control for CONTROLLER_HALT.
 *
 * S3 requires CONTROLLER_HALT to be 0, which a stuck-at-0 bit would also
 * pass, so this step makes the same bit go to 1: an address no target answers
 * is NACKed, which sets the NACK controller event and halts the FSM.
 * CONTROLLER_HALT follows the controller events register and is not
 * write-1-to-clear, so clearing the events must clear it.
 *
 * Runs last: it leaves the controller needing recovery.
 */
static void step_s6_controller_halt_control(void) {
    uint32_t base = i2c_get_base(CONTROLLER_IDX);
    i2c__INTR_STATE_t intr;
    i2c__CONTROLLER_EVENTS_t events = {.w = 0};
    i2c__STATUS_t status = {.w = 0};
    i2c__FDATA_t fdata = {.w = 0};
    uint32_t halt_status_at_nack;
    uint32_t i;
    int ret;

    simputs("STEP S6: NACK positive control for INTR_STATE.CONTROLLER_HALT\n");

    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0), 0xFu);

    intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
    if (intr.f.CONTROLLER_HALT != 0) {
        fail_with(0xBAD00070, "CONTROLLER_HALT already set before the NACK control");
    }

    ret = i2c_controller_wait_idle(CONTROLLER_IDX, I2C_WAIT_BOUND);
    if (ret != I2C_OK) {
        fail_with(0xBAD00071, "controller not idle before the NACK control");
    }

    fdata.f.FBYTE = (UNUSED_ADDR << 1) | 0x0u;
    fdata.f.START = 1;
    fdata.f.STOP = 1;
    fdata.f.NAKOK = 0; /* NAKOK would suppress exactly the halt this proves */
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0), fdata.w);

    halt_status_at_nack = 0;
    for (i = 0; i < I2C_WAIT_BOUND; i++) {
        events.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0));
        status.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0));
        if (events.f.NACK != 0) {
            halt_status_at_nack = status.w;
            break;
        }
    }
    if (i >= I2C_WAIT_BOUND) {
        simputs("  ERROR: no NACK event from the unanswered address after ");
        simputshex32("", I2C_WAIT_BOUND);
        simputs(" polls, CONTROLLER_EVENTS=");
        simputshex32("", events.w);
        simputs(" STATUS=");
        simputshex32("", status.w);
        simputs("\n");
        write_scratch(0, 0xBAD00072);
        test_fail(0);
    }

    intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
    if (intr.f.CONTROLLER_HALT != 1) {
        simputs("  ERROR: CONTROLLER_HALT did not set on an unhandled NACK, INTR_STATE=");
        simputshex32("", intr.w);
        simputs(" CONTROLLER_EVENTS=");
        simputshex32("", events.w);
        simputs("\n");
        write_scratch(0, 0xBAD00073);
        test_fail(0);
    }

    /* Clearing the events is the documented acknowledgement; the halt must
     * follow it down. */
    i2c_wr(base, SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0), 0xFu);

    intr.w = i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0));
    if (intr.f.CONTROLLER_HALT != 0) {
        simputs("  ERROR: CONTROLLER_HALT still set after clearing CONTROLLER_EVENTS, "
                "INTR_STATE=");
        simputshex32("", intr.w);
        simputs(" CONTROLLER_EVENTS=");
        simputshex32("", i2c_rd(base, SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0)));
        simputs("\n");
        write_scratch(0, 0xBAD00074);
        test_fail(0);
    }

    simputs("  CHK-CTRL-HALT-CONTROL: unanswered address NACKed after ");
    simputshex32("", i);
    simputs(" polls, STATUS at NACK=");
    simputshex32("", halt_status_at_nack);
    simputs(" INTR_STATE.CONTROLLER_HALT 0->1->0 across CONTROLLER_EVENTS clear\n");
}

int main(void) {
    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};
    i2c_timing_config_t computed_timing;
    int ret;

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

    write_scratch(1, 0x00000060);
    step_s6_controller_halt_control();
    write_scratch(1, 0x00000061);

    write_scratch(1, 0x00000090);
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n## SMC_I2C_001 evidence tokens emitted ##\n");
    write_scratch(0, TEST_PASS);
    test_pass(0);
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
