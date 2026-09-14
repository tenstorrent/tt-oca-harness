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
 *
 * The stretch itself is a *duration* on the SCL pin, which firmware cannot see:
 * every register this core exposes reports the FIFO level that causes the
 * stretch, not the clock that results from it. So the firmware parks at two
 * handshake markers -- one while the FIFO is full and one right after the ACQ
 * reset -- and the cocotb sequence samples the target's SCL driver across both
 * windows. See smc_i2c_acq_fifo_stretch_reset.py.
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

/* Bounds are stated as a simulated-time budget and converted to loop iterations
 * here, in one place, instead of being bare counts nobody can check. One poll
 * iteration that performs a single MMIO read costs ~430 ns of simulated time on
 * this testbench (measured this campaign), so a budget in nanoseconds can be
 * compared against the bus timing this test programs: Standard mode off a 10 ns
 * core clock gives tlow=470, thigh=490, i.e. an SCL period of 1000 cycles =
 * 10 us per bit and ~90 us per byte. */
#define POLL_NS_PER_ITER 430u
#define POLL_ITERS_FOR_NS(ns) (((ns) / POLL_NS_PER_ITER) + 1u)

/* 5 ms. The longest wait guarded by this bound is controller-idle after the
 * abort, ~300 us in the reference run, so this is >15x the observed worst case
 * while still expiring inside a normal job. */
#define POLL_TIMEOUT POLL_ITERS_FOR_NS(5000000u)
/* 20 ms. STATUS.ACQFULL asserts only after the target has accepted enough of
 * the long write to leave two ACQ entries free, i.e. after ~62 bytes have
 * crossed the bus. At standard mode that is 62 x 9 bit times of ~10 us, about
 * 5.6 ms at the nominal periph clock and ~6.7 ms at the slowest one the bench
 * randomises, so the 5 ms POLL_TIMEOUT above would expire inside a healthy
 * fill; this bound is ~3x the slowest fill and still expires inside a job. */
#define ACQ_FILL_TIMEOUT POLL_ITERS_FOR_NS(20000000u)
/* ~110 us, about 11 SCL periods. If the target has not returned to idle within
 * that many bit times the discarded long-write tail is still in flight, and the
 * target is force-disabled instead of waited on. */
#define TARGET_IDLE_PROBE POLL_ITERS_FOR_NS(110000u)
/* ~5 ms. The sequence notices a marker within its 5 us poll cadence and then
 * samples SCL across a window of ~3 byte times (~282 us), so its round trip is
 * a few hundred microseconds; 5 ms is >15x that and still fails closed. */
#define TB_ACK_BOUND POLL_ITERS_FOR_NS(5000000u)

/* Firmware <-> sequence handshake. scratch[4] carries the sequence's ACK.
 * scratch[2] is the virtual-console stream and scratch[3] the error count, so
 * the observation payload lives in 5..7. */
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

/* The tlow the DUT is actually running, read back out of its own timing
 * register. The sequence turns this into nanoseconds and uses it as the
 * yardstick for "SCL was low longer than a bit period", so the threshold comes
 * from the programmed hardware rather than from a constant transcribed here. */
static uint32_t get_timing_tlow(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    i2c__TIMING0_t timing0 = {.w = read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR(0) -
                                                    SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    return timing0.f.TLOW;
}

/* Publish a marker and block until the sequence acknowledges it, so the
 * sequence can sample the SCL pin while the DUT is held in the state under
 * proof. Fails closed: an ACK that never arrives ends the phase with a named
 * error instead of letting the firmware run past the observation window. */
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

/* Wait until the target itself says it has no room left.
 *
 * The gate is STATUS.ACQFULL alone. It is driven from
 * acq_fifo_full = !acq_fifo_plenty_space (i2c_core.sv:274,
 * i2c_target_fsm.sv:1043), which is `remainder <= 2` against
 * smc_config_pkg::I2C_TARGET_RX_FIFO_DEPTH, so a level threshold copied out of
 * the RTL would be the same expression twice and move with it under any change
 * of depth or margin. What is left is the DUT's own statement that it is out
 * of room; the level is reported, not used as a gate.
 *
 * INTR_STATE.ACQ_STRETCH is not used here: it is a status-type bit that
 * follows the stretch condition (INTR_ENABLE masks only irq_o), so it would
 * add nothing over STATUS.ACQFULL, which is the DUT's own out-of-room flag.
 */
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

    /* Report the last sample the loop actually took, not a fresh read: a
     * re-read describes a later state than the one that timed out. */
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

static int send_long_write_until_target_stretches(uint32_t *acqlvl_out) {
    uint8_t long_data[LONG_WRITE_LEN];

    for (uint32_t i = 0; i < LONG_WRITE_LEN; i++) {
        long_data[i] = (uint8_t)(0x40u + i);
    }

    simputs("  Controller sending long write to fill target ACQ FIFO...\n");
    int ret = i2c_controller_write_with_header_nonblock(CONTROLLER_IDX, TARGET_ADDR, long_data,
                                                        LONG_WRITE_LEN);
    if (ret != I2C_OK) {
        /* Fail here rather than log and continue: the ACQ level observed
         * downstream is graded against the number of offered bytes, so "70
         * bytes were offered" has to be a fact the later check can rest on. */
        simputshex32("  ERROR: Long write enqueue failed, ret=", (uint32_t)ret);
        simputs("\n");
        return ret;
    }

    return wait_for_acq_stretch(TARGET_IDX, acqlvl_out);
}

/* Hand the sequence a window in which to sample SCL, with the numbers it needs
 * to interpret what it sees. */
static int publish_stretch_observation(uint32_t acqlvl) {
    write_scratch(5, acqlvl);
    write_scratch(6, get_timing_tlow(CONTROLLER_IDX));
    write_scratch(7, get_i2c_status(TARGET_IDX).w);
    return tb_sync(SCR_STRETCH_OBS);
}

/* g_i2c_acq_reset_needed_drain is deliberately not published here: the caller
 * has already returned an error if it was set, so a sequence reading it would
 * only ever see 0 and would be reporting a constant dressed up as evidence. It
 * is on the firmware console line instead, where it can be either value. */
static int publish_release_observation(uint32_t lvl_before, uint32_t lvl_after) {
    write_scratch(5, lvl_before);
    write_scratch(6, lvl_after);
    write_scratch(7, get_i2c_status(TARGET_IDX).w);
    return tb_sync(SCR_RELEASE_OBS);
}

static int release_stretch_and_discard_long_write_tail(uint32_t acqlvl_at_stretch) {
    int ret;

    /*
     * Proof stimulus: ACQ FIFO reset releases automatic SCL stretch.
     * Then recover the in-progress long write like tx_stretch_timeout_recovery
     * (controller disable -> STOP, target disable -> idle, reinit both).
     */

    /* Window 1: the target is out of room and holding SCL. The sequence samples
     * i2c0_scl_ip_o across this window and requires a continuous low run longer
     * than a programmed bit period; a level read cannot tell a stretch from an
     * ordinary SCL low phase, and a duration can. */
    ret = publish_stretch_observation(acqlvl_at_stretch);
    if (ret != I2C_OK) {
        return ret;
    }

    simputs("  ACQ reset (stretch release) then controller disable...\n");
    /* Bracket the reset that is actually under test.
     *
     * i2c_reset_fifos() drains the FIFO by hand when ACQRST leaves entries
     * behind, so a level read taken after the helper alone would be the
     * helper's doing, not the hardware's. g_i2c_acq_reset_needed_drain
     * distinguishes the two.
     */
    {
        i2c__STATUS_t status_before = get_i2c_status(TARGET_IDX);
        uint32_t lvl_before = get_acq_level(TARGET_IDX);
        uint32_t lvl_after;

        /* Entry condition for the reset, stated without a transcribed depth:
         * the target must still be reporting no room -- its own flow-control
         * signal, not a copy of the RTL's depth-minus-margin arithmetic.
         *
         * The upper bound reconciles the reading against the stimulus that was
         * confirmed enqueued above: at most the 70 data bytes plus the address
         * and length-header entries. It is slack today, because the ACQ FIFO is
         * shallower than the write is long, and it becomes live the moment
         * either number moves -- which is the point of stating it against the
         * stimulus rather than against the FIFO. */
        if (!status_before.f.ACQFULL || lvl_before == 0u ||
            lvl_before > (uint32_t)(LONG_WRITE_LEN + 2)) {
            simputshex32("  ERROR: ACQ not full-and-consistent before reset, acqlvl=", lvl_before);
            simputshex32(" status=", status_before.w);
            simputs("\n");
            return I2C_ERROR;
        }

        /* This is the one reset in the suite whose repair path is inspected
         * below rather than trusted, so take the driver's fail-closed gate off
         * for exactly this call and report the outcome ourselves. */
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
        /* What is provable here, and what is not.
         *
         * "ACQLVL == 0 immediately after ACQRST" is not a property this position
         * can assert. Releasing the stretch is the *point* of the reset, and the
         * controller resumes clocking out the tail of the long write the moment
         * it is released -- so entries start arriving again before firmware can
         * read the level back. Requiring an exact zero here makes the verdict a
         * race between the APB read-back and the I2C bit rate, which is what the
         * measured run showed: 1 entry of 62 had already re-landed.
         *
         * What *is* provable is the thing the must-fix actually asked for --
         * that the hardware reset, not the driver's software drain, did the
         * emptying. The two are told apart by how much the drain removed:
         * a refill is a couple of entries, whereas an ACQRST that did nothing
         * leaves the drain to remove substantially all of lvl_before.
         *
         * The bound is stated against the pre-reset depth rather than as a tuned
         * constant, so it stays live if the FIFO depth or the stimulus length
         * moves: the drain may account for at most a quarter of what was in the
         * FIFO. At the measured 1-of-62 there is 15x of margin, and a reset that
         * silently stopped working (drained == lvl_before) misses by 4x. */
        if (g_i2c_acq_reset_needed_drain && (g_i2c_acq_reset_drained * 4u) > lvl_before) {
            simputs("  ERROR: ACQRST did not empty the FIFO; the empty level above was\n");
            simputs("         produced by the driver's manual drain, not by the reset\n");
            simputshex32("         entries drained by hand=", g_i2c_acq_reset_drained);
            simputshex32(" of pre-reset level ", lvl_before);
            simputs("\n");
            return I2C_ERROR;
        }
        if (g_i2c_acq_reset_needed_drain) {
            /* Not a failure -- the post-release refill described above. Recorded
             * so the margin is visible in the log and a drift toward the bound
             * is noticed before it trips. */
            simputshex32("  ACQRST emptied the FIFO; post-release refill=",
                         g_i2c_acq_reset_drained);
            simputshex32(" of ", lvl_before);
            simputs("\n");
        }

        /* Window 2: same measurement, immediately after the reset and before
         * the controller is disabled, where the sequence requires the absence
         * of any such low run. Window 1 proves the probe can read 0 and
         * window 2 proves it can read 1, so neither window can pass on a dead
         * or stuck net.
         *
         * The reset and the disable need not be back-to-back: the recovery
         * below force-disables the target when the tail is still in flight,
         * which is the path taken with ~24 us of simputs in the gap. The window
         * costs ~282 us more, i.e. about 3 of the ~10 bytes still queued in FMT
         * go out before the disable, and the discard path handles them the
         * same way. */
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

    while (true) {
        __asm__("wfi");
    }

    return 0;
}
