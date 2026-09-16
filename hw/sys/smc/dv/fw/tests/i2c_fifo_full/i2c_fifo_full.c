/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_fifo_full.c
 * @brief I2C FIFO fill/reset test for the four FIFOs of an I2C pair
 *
 * I2C_0 runs as controller and I2C_1 as target, on the same bus, so every leg
 * below is driven entirely from firmware.
 *
 * Scope, stated per FIFO rather than as "all four FIFOs full":
 *
 *   FMT (controller): filled to the configured depth by software stores until
 *     STATUS.FMTFULL asserts, then FMTRST. FMTLVL and the store count are both
 *     asserted against I2C_CONTROLLER_TX_FIFO_DEPTH, so a FIFO that reports full
 *     at some other depth fails here instead of passing on the flag alone.
 *   TX (target): the same walk against I2C_TARGET_TX_FIFO_DEPTH, then TXRST.
 *   RX (controller): filled by a *real* read transfer from the target, not by
 *     software stores -- nothing but the bus can put an entry in this FIFO. The
 *     level is proven non-zero (exactly the requested byte count) before RXRST
 *     is applied and the level is proven back to zero afterwards. RX *full* is
 *     out of scope: reaching it needs a 64-byte read, ~5.8 ms of standard-mode
 *     bus time, and nothing here observes STATUS.RXFULL asserted.
 *   ACQ (target): filled by a real write transfer from the controller. The
 *     entry count is asserted exactly (START + payload + STOP) before ACQRST and
 *     proven back to zero afterwards. ACQ *full* and the SCL stretch it causes
 *     are out of scope here and are proven in i2c_acq_fifo_stretch_reset.
 *
 * Why the RX and ACQ legs transfer at all: i2c_reset_fifos() repairs a FIFO that
 * the hardware reset failed to empty, by popping RDATA/ACQDATA in software. So
 * "the FIFO is empty after the reset" is a post-condition the helper itself can
 * manufacture, and asserting it straight after the helper cannot fail on any
 * RTL. Two things fix that: the level is made non-zero by a transfer the helper
 * cannot fake, and g_i2c_rx_reset_needed_drain / g_i2c_acq_reset_needed_drain
 * are read back so a repaired FIFO is reported as a failure rather than
 * laundered into a PASS.
 *
 * Leg markers in scratch[1] and the 0xBAD000xx codes in scratch[0] identify the
 * FIFO, not the execution order: FMT 0x40, RX 0x50, TX 0x60, ACQ 0x70. 0x80 and
 * 0x90 are avoided because the shared driver publishes them from inside
 * i2c_target_transmit() and i2c_controller_read() (i2c_opentitan.c), which this
 * test calls, so a hang parked there would be ambiguous.
 *
 * The two bus legs run first, while both instances are in their post-init state.
 * The two software fill legs run last and stop their FIFO's hardware consumer --
 * the controller FSM is disabled for the FMT fill, and nothing reads the target
 * while its TX FIFO is filled -- so in those two legs the level is the store
 * count and no bus traffic is left in flight behind them.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

// Test parameters
#define CONTROLLER_IDX 0 // I2C_0 for Controller mode (FMT, RX FIFO)
#define TARGET_IDX 1     // I2C_1 for Target mode (TX, ACQ FIFO)
#define TARGET_ADDR 0x10 // 7-bit target address programmed into I2C_1

/* Depths come from the shared header, which transcribes smc_config_pkg.sv:23-26
 * in one place, instead of being re-copied per test. */
#define FMT_FIFO_DEPTH I2C_CONTROLLER_TX_FIFO_DEPTH
#define TX_FIFO_DEPTH I2C_TARGET_TX_FIFO_DEPTH

/* Bus stimulus for the two FIFOs that only the bus can fill. Both are far below
 * the 64-entry depth on purpose -- see the scope note in the file header. */
#define RX_READ_LEN 8u
#define ACQ_WRITE_LEN 8u
/* With CTRL.ACQ_START_STOP_EN set the target FSM pushes an AcqStart entry
 * carrying the address byte and an AcqStop entry around the payload, so a write
 * of N bytes lands N + 2 entries (same accounting as i2c_p0_fifo.c:65). */
#define ACQ_EXPECTED_ENTRIES (1u + ACQ_WRITE_LEN + 1u)

/* One accessor for every register in this file. The per-instance stride is the
 * same 0x200 in SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR() and in every per-register
 * macro (smc_addr.h:54,631...), so indexing the generated register macro is both
 * shorter and correct for idx != 0, unlike a base-plus-offset(0) expression. */
#define I2C_REG(idx, REG) (SMC_TOP_SMC_I2C_WRAP_I2C_##REG##_BASE_ADDR(idx))

/* Poll bounds, in loop iterations.
 *
 * Sized from measured cost, not guessed. A single-register poll iteration costs
 * 0.44-1.15 us of simulation in this testbench (the measurement recorded on
 * I2C_TIMEOUT_DEFAULT in i2c_opentitan.h:88-105). Standard mode off a 10 ns core
 * clock puts SCL at 100 kHz, i.e. ~10 us per bit and ~90 us per byte, so the
 * longest wait below -- an 8-byte transfer plus its address and STOP -- is
 * ~0.9 ms.
 *
 * 4000 iterations is ~1.8-4.6 ms: 2-5x that worst case, and it expires well
 * inside the testbench's 20 ms completion bound
 * (tb_wrap_cocotb/tests/smc_i2c_fifo_full.py:97), so the diagnostics behind
 * these bounds are reachable instead of being preempted by the harness.
 *
 * I2C_TIMEOUT_DEFAULT is deliberately not used here: it is 200000 iterations
 * (~90-230 ms), an order of magnitude past the harness bound, so a failure
 * branch guarded by it can never print.
 */
#define XFER_POLL_BOUND 4000u
#define IDLE_POLL_BOUND 4000u

/**
 * @brief Enable I2C Wrapper Control (LEVEL 1)
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);
}

static uint32_t fmt_level(uint32_t idx) {
    i2c__HOST_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, HOST_FIFO_STATUS))};

    return (uint32_t)fifo_status.f.FMTLVL;
}

static uint32_t rx_level(uint32_t idx) {
    i2c__HOST_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, HOST_FIFO_STATUS))};

    return (uint32_t)fifo_status.f.RXLVL;
}

static uint32_t tx_level(uint32_t idx) {
    i2c__TARGET_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};

    return (uint32_t)fifo_status.f.TXLVL;
}

static uint32_t acq_level(uint32_t idx) {
    i2c__TARGET_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};

    return (uint32_t)fifo_status.f.ACQLVL;
}

/* Report a FIFO reset that only took because i2c_reset_fifos() repaired the FIFO
 * in software.
 *
 * The helper drains RX/ACQ by hand and re-applies FMTRST/TXRST when the first
 * attempt leaves entries behind, so every "level is 0 after reset" compare in
 * this file is satisfied either by the hardware reset or by that repair, and the
 * level alone cannot tell them apart. The helper records which happened, per
 * call, and fails closed by default; this restates the same contract at the
 * point where each leg depends on it, and stays live if a future test clears
 * g_i2c_reset_repair_allowed for a window.
 */
static int check_reset_took(uint32_t needed_repair, uint32_t residual, const char *what) {
    if (needed_repair) {
        simputs("  ERROR: ");
        simputs(what);
        simputs(" did not take -- the driver emptied the FIFO in software, so any\n");
        simputs("         'empty after reset' below would be that repair's doing. residual=");
        simputshex32("", residual);
        simputs("\n");
        return I2C_ERROR;
    }
    return I2C_OK;
}

/**
 * @brief Test FMT FIFO full and empty states
 *
 * The controller FSM is stopped for the duration, so software stores are the
 * only producer, there is no consumer, and every level asserted here is the
 * store count. See the comment at the disable below for why that is not a
 * convenience.
 *
 * The controller is left disabled on return: this is the last leg that touches
 * I2C_0, and re-enabling it would only put the filler bytes of a subsequent
 * fill back on the bus.
 */
static int test_fmt_fifo_full_empty(uint32_t idx) {
    uint32_t pushed = 0;
    uint32_t level;
    bool full_seen = false;
    int ret;

    simputs("\n=== Test FMT FIFO Full/Empty ===\n");

    /* This leg stuffs the FMT FIFO with entries that are never transmitted, so
     * it must not start on top of an in-flight transaction from an earlier leg.
     */
    if (!i2c_controller_is_idle(idx)) {
        simputs("  ERROR: controller not idle before the FMT fill\n");
        return I2C_ERROR;
    }

    /* Stop the controller FSM before filling, so the FMT FIFO has exactly one
     * producer and no consumer and every level below is the store count.
     *
     * The FSM leaves Idle as soon as the FMT FIFO is non-empty and the bus is
     * free (i2c_controller_fsm.sv:672-676) -- a START flag is not required -- so
     * with the controller enabled it starts clocking these filler bytes onto the
     * bus and pops entries out from under the fill. It only failed to race the
     * old version of this leg because a byte takes ~90 us on the wire while the
     * whole fill takes ~64 us; that margin is not a property anything asserts.
     * ENABLEHOST gates neither the FDATA write path (i2c_core.sv:379) nor
     * STATUS.FMTFULL (:258), and only FMTRST clears the FIFO (:415), so nothing
     * this leg checks depends on the FSM running. */
    i2c_controller_disable(idx);

    // Reset FMT FIFO first -- the anchor every level below is counted from
    i2c_reset_fifos(idx, false, true, false, false);
    ret = check_reset_took(g_i2c_fmt_reset_needed_retry, g_i2c_fmt_reset_residual, "setup FMTRST");
    if (ret != I2C_OK) return ret;

    i2c__STATUS_t status_initial = {.w = read_reg(I2C_REG(idx, STATUS))};
    if (!status_initial.f.FMTEMPTY) {
        simputs("  ERROR: FMT FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    level = fmt_level(idx);
    if (level != 0) {
        simputshex32("  ERROR: FMTLVL after the anchor reset is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: FMT FIFO is empty after reset\n");

    /* Fill to full. STATUS.FMTFULL is read before each push because a store into
     * a full FMT FIFO is dropped silently (fmt_fifo_wvalid ignores wready,
     * i2c_core.sv:379), so an unchecked push would lose data instead of failing.
     *
     * The cap is depth + 6 pushes and the flag is then asserted, which keeps this
     * fail-closed against the depth itself: if the FIFO were the IP default of
     * 268 -- or anything above the cap -- the loop would run out without seeing
     * full and this leg would fail rather than quietly pass. */
    for (uint32_t i = 0; i < FMT_FIFO_DEPTH + 6u; i++) {
        i2c__STATUS_t status_check = {.w = read_reg(I2C_REG(idx, STATUS))};
        if (status_check.f.FMTFULL) {
            full_seen = true;
            break;
        }

        i2c__FDATA_t fdata = {.w = 0};
        fdata.f.FBYTE = (uint8_t)(0xAA + i);
        write_reg(I2C_REG(idx, FDATA), fdata.w);
        pushed++;
    }

    if (!full_seen) {
        simputshex32("  ERROR: STATUS.FMTFULL never asserted; entries stored=", pushed);
        simputshex32(", cap=", (uint32_t)(FMT_FIFO_DEPTH + 6u));
        simputshex32(", FMTLVL=", fmt_level(idx));
        simputs("\n");
        return I2C_ERROR;
    }

    /* Two independent statements about the same fill: how many entries this test
     * stored, and what the DUT says it holds. The flag alone cannot distinguish
     * a FIFO that filled to the configured depth from one that reported full at
     * some other depth. */
    if (pushed != FMT_FIFO_DEPTH) {
        simputshex32("  ERROR: FMTFULL asserted after ", pushed);
        simputshex32(" stores, expected the configured depth ", (uint32_t)FMT_FIFO_DEPTH);
        simputs("\n");
        return I2C_ERROR;
    }
    level = fmt_level(idx);
    if (level != FMT_FIFO_DEPTH) {
        simputshex32("  ERROR: FMTLVL at FMTFULL is ", level);
        simputshex32(" != configured depth ", (uint32_t)FMT_FIFO_DEPTH);
        simputs("\n");
        return I2C_ERROR;
    }
    simputs("  PASS: FMT FIFO STATUS.FMTFULL is set at FMTLVL=");
    simputshex32("", level);
    simputshex32(" after ", pushed);
    simputs(" stores\n");

    // Reset FMT FIFO to empty -- this reset is the one under test
    i2c_reset_fifos(idx, false, true, false, false);
    ret = check_reset_took(g_i2c_fmt_reset_needed_retry, g_i2c_fmt_reset_residual, "FMTRST");
    if (ret != I2C_OK) return ret;

    i2c__STATUS_t status_empty = {.w = read_reg(I2C_REG(idx, STATUS))};
    if (!status_empty.f.FMTEMPTY) {
        simputs("  ERROR: FMT FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    if (status_empty.f.FMTFULL) {
        simputs("  ERROR: FMT FIFO should not be full after reset\n");
        return I2C_ERROR;
    }
    level = fmt_level(idx);
    if (level != 0) {
        simputshex32("  ERROR: FMTLVL after FMTRST is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: FMTRST took the FIFO from full back to FMTLVL=0, FMTEMPTY set\n");

    simputs("  PASS: FMT FIFO test PASSED\n");
    return I2C_OK;
}

/**
 * @brief Start a controller read without popping RDATA.
 *
 * Both FMT entries are written back-to-back, as i2c_controller_read() does
 * (i2c_opentitan.c:846-870): the OpenTitan controller FSM drops back to Idle
 * when fmt_fifo_depth_i == 1 (i2c_controller_fsm.sv:960-961), so the READ entry
 * has to be queued behind the address entry before the FSM pops the first one.
 *
 * Unlike i2c_controller_read() this deliberately does not drain the RX FIFO --
 * leaving the received bytes in it is the whole point of the RX leg.
 */
static void rx_start_read(uint32_t idx, uint8_t addr, uint32_t len) {
    i2c__FDATA_t fdata = {.w = 0};

    fdata.f.FBYTE = (uint8_t)((addr << 1) | 0x1u); // START + address, R/W = read
    fdata.f.START = 1;
    fdata.f.READB = 0;
    write_reg(I2C_REG(idx, FDATA), fdata.w);

    fdata.w = 0;
    fdata.f.FBYTE = (uint8_t)(len & 0xFFu); // byte count for this read
    fdata.f.READB = 1;
    fdata.f.RCONT = 0; // NACK the last byte
    fdata.f.STOP = 1;
    write_reg(I2C_REG(idx, FDATA), fdata.w);
}

/**
 * @brief Test the controller RX FIFO: real fill, then RXRST.
 *
 * The target answers a read out of its TX FIFO, so the entries in RX arrive over
 * the bus. That is the state i2c_reset_fifos() cannot manufacture, and without
 * it the "empty after reset" compares at the end of this function are satisfied
 * by the driver's own repair path rather than by the DUT.
 */
static int test_rx_fifo_fill_and_reset(uint32_t ctrl_idx, uint32_t tgt_idx) {
    uint8_t tx_data[RX_READ_LEN];
    uint32_t polls = 0;
    uint32_t level;
    uint32_t preloaded;
    int ret;

    simputs("\n=== Test RX FIFO Fill/Reset ===\n");

    for (uint32_t i = 0; i < RX_READ_LEN; i++) {
        tx_data[i] = (uint8_t)(0x51u + i);
    }

    // Anchor: the level this leg counts from, and the reset that produced it
    i2c_reset_fifos(ctrl_idx, true, false, false, false);
    ret = check_reset_took(g_i2c_rx_reset_needed_drain, g_i2c_rx_reset_residual, "setup RXRST");
    if (ret != I2C_OK) return ret;
    level = rx_level(ctrl_idx);
    if (level != 0) {
        simputshex32("  ERROR: RXLVL before the read is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }

    /* The target must be able to answer, and its ACQ FIFO must be empty when the
     * read request arrives or it stretches SCL instead of replying
     * (i2c_read_sanity.c:425-443). */
    i2c_reset_fifos(tgt_idx, false, false, true, true);
    ret = check_reset_took(g_i2c_acq_reset_needed_drain, g_i2c_acq_reset_residual,
                           "target ACQRST before the read");
    if (ret != I2C_OK) return ret;
    ret = check_reset_took(g_i2c_tx_reset_needed_retry, g_i2c_tx_reset_residual,
                           "target TXRST before the read");
    if (ret != I2C_OK) return ret;

    preloaded = i2c_target_transmit(tgt_idx, tx_data, RX_READ_LEN);
    if (preloaded != RX_READ_LEN) {
        simputshex32("  ERROR: preloaded ", preloaded);
        simputshex32(" of ", (uint32_t)RX_READ_LEN);
        simputs(" bytes into the target TX FIFO\n");
        return I2C_ERROR;
    }

    /* TARGET_EVENTS is cleared *after* the preload, not before: filling the TX
     * FIFO can itself raise an event, and an unhandled one makes the target
     * stretch instead of answering the read request
     * (i2c_p0_rdwr.c:425-433, same ordering). */
    if (i2c_get_target_events(tgt_idx) != 0) {
        i2c_clear_target_events(tgt_idx, 0xFFFFFFFF);
    }

    /* rx_start_read() needs both entries to fit; the FMT FIFO is untouched at
     * this point in the run, so this is a checkable precondition. */
    level = fmt_level(ctrl_idx);
    if (level != 0) {
        simputshex32("  ERROR: FMTLVL before the read request is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }

    simputs("  Controller reading ");
    simputshex32("", (uint32_t)RX_READ_LEN);
    simputs(" bytes from the target...\n");
    rx_start_read(ctrl_idx, TARGET_ADDR, RX_READ_LEN);

    level = rx_level(ctrl_idx);
    while (level < RX_READ_LEN && polls < XFER_POLL_BOUND) {
        level = rx_level(ctrl_idx);
        polls++;
    }
    if (level != RX_READ_LEN) {
        i2c__STATUS_t status_now = {.w = read_reg(I2C_REG(ctrl_idx, STATUS))};

        simputshex32("  ERROR: RXLVL ", level);
        simputshex32(" != the ", (uint32_t)RX_READ_LEN);
        simputshex32(" bytes requested, after polls=", polls);
        simputshex32(" (STATUS=", status_now.w);
        simputshex32(", controller events=", i2c_get_controller_events(ctrl_idx));
        simputshex32(", target TXLVL=", tx_level(tgt_idx));
        simputs(")\n");
        if (level == 0) {
            simputs("  [Diagnosis] no byte reached the RX FIFO -- the read was NACKed or the\n");
            simputs("              target never answered\n");
        }
        return I2C_ERROR_TIMEOUT;
    }

    /* The empty flag with a known non-empty FIFO: the RX leg's positive control. */
    i2c__STATUS_t status_filled = {.w = read_reg(I2C_REG(ctrl_idx, STATUS))};
    if (status_filled.f.RXEMPTY) {
        simputshex32("  ERROR: STATUS.RXEMPTY is set while RXLVL is ", level);
        simputs("\n");
        return I2C_ERROR;
    }
    if (status_filled.f.RXFULL) {
        simputshex32("  ERROR: STATUS.RXFULL is set at RXLVL ", level);
        simputshex32(" of depth ", (uint32_t)I2C_CONTROLLER_RX_FIFO_DEPTH);
        simputs("\n");
        return I2C_ERROR;
    }
    simputs("  PASS: a real read left RXLVL=");
    simputshex32("", level);
    simputs(" with RXEMPTY clear\n");

    /* Let the transfer finish before resetting. While the controller is still
     * clocking bytes in, "RXLVL is 0 after RXRST" is a race between the reset and
     * the next byte rather than a property of RXRST, so the producer is stopped
     * first and the level is re-read to prove nothing drained on its own. */
    ret = i2c_controller_wait_idle(ctrl_idx, IDLE_POLL_BOUND);
    if (ret != I2C_OK) {
        simputshex32("  ERROR: controller not idle after the read, STATUS=",
                     read_reg(I2C_REG(ctrl_idx, STATUS)));
        simputs("\n");
        return ret;
    }
    level = rx_level(ctrl_idx);
    if (level != RX_READ_LEN) {
        simputshex32("  ERROR: RXLVL changed to ", level);
        simputshex32(" while the bus went idle; nothing in this leg pops RDATA, expected ",
                     (uint32_t)RX_READ_LEN);
        simputs("\n");
        return I2C_ERROR;
    }

    // The reset under test, applied to a FIFO that is provably non-empty
    i2c_reset_fifos(ctrl_idx, true, false, false, false);
    ret = check_reset_took(g_i2c_rx_reset_needed_drain, g_i2c_rx_reset_residual, "RXRST");
    if (ret != I2C_OK) return ret;

    i2c__STATUS_t status_empty = {.w = read_reg(I2C_REG(ctrl_idx, STATUS))};
    if (!status_empty.f.RXEMPTY) {
        simputs("  ERROR: RX FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    if (status_empty.f.RXFULL) {
        simputs("  ERROR: RX FIFO should not be full after reset\n");
        return I2C_ERROR;
    }
    level = rx_level(ctrl_idx);
    if (level != 0) {
        simputshex32("  ERROR: RXLVL after RXRST is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: RXRST took the FIFO from ");
    simputshex32("", (uint32_t)RX_READ_LEN);
    simputs(" entries back to RXLVL=0, RXEMPTY set\n");
    simputs("  PASS: RX FIFO test PASSED\n");
    return I2C_OK;
}

/**
 * @brief Test TX FIFO full and empty states
 *
 * No controller reads this target during this leg, so software stores are the
 * only producer and TXRST is the only consumer.
 */
static int test_tx_fifo_full_empty(uint32_t idx) {
    uint32_t pushed = 0;
    uint32_t level;
    bool full_seen = false;
    int ret;

    simputs("\n=== Test TX FIFO Full/Empty ===\n");

    if (!i2c_target_is_idle(idx)) {
        simputs("  ERROR: target not idle before the TX fill\n");
        return I2C_ERROR;
    }

    // Reset TX FIFO first -- the anchor every level below is counted from
    i2c_reset_fifos(idx, false, false, true, false);
    ret = check_reset_took(g_i2c_tx_reset_needed_retry, g_i2c_tx_reset_residual, "setup TXRST");
    if (ret != I2C_OK) return ret;

    i2c__STATUS_t status_initial = {.w = read_reg(I2C_REG(idx, STATUS))};
    if (!status_initial.f.TXEMPTY) {
        simputs("  ERROR: TX FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    level = tx_level(idx);
    if (level != 0) {
        simputshex32("  ERROR: TXLVL after the anchor reset is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: TX FIFO is empty after reset\n");

    /* Same construction as the FMT leg: the full flag is read before each store
     * so no byte is silently dropped, and the cap keeps the leg fail-closed
     * against a depth larger than the one asserted below. */
    for (uint32_t i = 0; i < TX_FIFO_DEPTH + 6u; i++) {
        i2c__STATUS_t status_check = {.w = read_reg(I2C_REG(idx, STATUS))};
        if (status_check.f.TXFULL) {
            full_seen = true;
            break;
        }

        i2c__TXDATA_t txdata = {.w = 0};
        txdata.f.DATA = (uint8_t)(0xBB + i);
        write_reg(I2C_REG(idx, TXDATA), txdata.w);
        pushed++;
    }

    if (!full_seen) {
        simputshex32("  ERROR: STATUS.TXFULL never asserted; entries stored=", pushed);
        simputshex32(", cap=", (uint32_t)(TX_FIFO_DEPTH + 6u));
        simputshex32(", TXLVL=", tx_level(idx));
        simputs("\n");
        return I2C_ERROR;
    }

    if (pushed != TX_FIFO_DEPTH) {
        simputshex32("  ERROR: TXFULL asserted after ", pushed);
        simputshex32(" stores, expected the configured depth ", (uint32_t)TX_FIFO_DEPTH);
        simputs("\n");
        return I2C_ERROR;
    }
    level = tx_level(idx);
    if (level != TX_FIFO_DEPTH) {
        simputshex32("  ERROR: TXLVL at TXFULL is ", level);
        simputshex32(" != configured depth ", (uint32_t)TX_FIFO_DEPTH);
        simputs("\n");
        return I2C_ERROR;
    }
    simputs("  PASS: TX FIFO STATUS.TXFULL is set at TXLVL=");
    simputshex32("", level);
    simputshex32(" after ", pushed);
    simputs(" stores\n");

    // Reset TX FIFO to empty -- this reset is the one under test
    i2c_reset_fifos(idx, false, false, true, false);
    ret = check_reset_took(g_i2c_tx_reset_needed_retry, g_i2c_tx_reset_residual, "TXRST");
    if (ret != I2C_OK) return ret;

    i2c__STATUS_t status_empty = {.w = read_reg(I2C_REG(idx, STATUS))};
    if (!status_empty.f.TXEMPTY) {
        simputs("  ERROR: TX FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    if (status_empty.f.TXFULL) {
        simputs("  ERROR: TX FIFO should not be full after reset\n");
        return I2C_ERROR;
    }
    level = tx_level(idx);
    if (level != 0) {
        simputshex32("  ERROR: TXLVL after TXRST is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: TXRST took the FIFO from full back to TXLVL=0, TXEMPTY set\n");

    simputs("  PASS: TX FIFO test PASSED\n");
    return I2C_OK;
}

/**
 * @brief Push a controller write of len bytes: START + address, payload, STOP.
 *
 * This is the same FDATA program i2c_controller_write() emits
 * (i2c_opentitan.c:659-706), reproduced here so that every wait in the ACQ leg
 * is bounded by XFER_POLL_BOUND. The driver's completion wait uses
 * I2C_TIMEOUT_DEFAULT (~90-230 ms), 5-10x the harness bound, so a transfer that
 * never completes would have the run killed by the testbench before any
 * FIFO-level diagnostic could print.
 *
 * STATUS.FMTFULL is polled before each push because an FDATA store into a full
 * FMT FIFO is dropped silently (i2c_core.sv:379), which would shorten the
 * payload -- and so the ACQ entry count -- with no error anywhere.
 */
static int acq_push_write(uint32_t idx, uint8_t addr, const uint8_t *data, uint32_t len) {
    for (uint32_t i = 0; i <= len; i++) {
        uint32_t polls = 0;
        i2c__FDATA_t fdata = {.w = 0};
        i2c__STATUS_t status = {.w = read_reg(I2C_REG(idx, STATUS))};

        while (status.f.FMTFULL && polls < XFER_POLL_BOUND) {
            status.w = read_reg(I2C_REG(idx, STATUS));
            polls++;
        }
        if (status.f.FMTFULL) {
            simputshex32("  ERROR: FMT FIFO stayed full before entry ", i);
            simputshex32(" of ", len + 1u);
            simputshex32(", FMTLVL=", fmt_level(idx));
            simputs("\n");
            return I2C_ERROR_TIMEOUT;
        }

        if (i == 0) {
            fdata.f.FBYTE = (uint8_t)((addr << 1) | 0x0u); // START + address, R/W = write
            fdata.f.START = 1;
        } else {
            fdata.f.FBYTE = data[i - 1];
            fdata.f.STOP = (i == len) ? 1 : 0;
        }
        write_reg(I2C_REG(idx, FDATA), fdata.w);
    }

    return I2C_OK;
}

/**
 * @brief Test the target ACQ FIFO: real fill, then ACQRST.
 *
 * The controller writes a known number of bytes to the target's address, so the
 * ACQ entries arrive over the bus -- the state i2c_reset_fifos() cannot
 * manufacture. Without it the "empty after reset" compares at the end of this
 * function are satisfied by the driver's own drain loop rather than by the DUT.
 */
static int test_acq_fifo_fill_and_reset(uint32_t ctrl_idx, uint32_t tgt_idx) {
    uint8_t wr_data[ACQ_WRITE_LEN];
    uint32_t polls = 0;
    uint32_t level;
    int ret;

    simputs("\n=== Test ACQ FIFO Fill/Reset ===\n");

    for (uint32_t i = 0; i < ACQ_WRITE_LEN; i++) {
        wr_data[i] = (uint8_t)(0xC1u + i);
    }

    /* Anchor: the level this leg counts from. The read leg before it leaves its
     * own START and STOP entries in the ACQ FIFO, so this reset is load-bearing
     * and the entry count asserted below is only attributable to the write that
     * follows it. */
    i2c_reset_fifos(tgt_idx, false, false, false, true);
    ret = check_reset_took(g_i2c_acq_reset_needed_drain, g_i2c_acq_reset_residual, "setup ACQRST");
    if (ret != I2C_OK) return ret;
    level = acq_level(tgt_idx);
    if (level != 0) {
        simputshex32("  ERROR: ACQLVL before the write is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    if (i2c_get_target_events(tgt_idx) != 0) {
        i2c_clear_target_events(tgt_idx, 0xFFFFFFFF);
    }

    i2c__CTRL_t target_ctrl = {.w = read_reg(I2C_REG(tgt_idx, CTRL))};
    if (!target_ctrl.f.ACQ_START_STOP_EN) {
        simputs("  ERROR: CTRL.ACQ_START_STOP_EN is 0 -- the entry count below assumes the\n");
        simputs("         AcqStart and AcqStop entries are pushed\n");
        return I2C_ERROR;
    }

    /* The FMT FIFO must be able to hold the whole program, and it is empty at
     * this point in the run, so this is a checkable precondition. */
    level = fmt_level(ctrl_idx);
    if (level != 0) {
        simputshex32("  ERROR: FMTLVL before the write is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }

    simputs("  Controller writing ");
    simputshex32("", (uint32_t)ACQ_WRITE_LEN);
    simputs(" bytes to the target...\n");
    ret = acq_push_write(ctrl_idx, TARGET_ADDR, wr_data, ACQ_WRITE_LEN);
    if (ret != I2C_OK) {
        simputshex32("  ERROR: could not enqueue the write, ret=", (uint32_t)ret);
        simputshex32(", controller events=", i2c_get_controller_events(ctrl_idx));
        simputs("\n");
        return ret;
    }

    /* START entry + payload + STOP entry, stated against the stimulus this test
     * issued rather than against anything read back from the DUT. */
    level = acq_level(tgt_idx);
    while (level < ACQ_EXPECTED_ENTRIES && polls < XFER_POLL_BOUND) {
        level = acq_level(tgt_idx);
        polls++;
    }
    if (level != ACQ_EXPECTED_ENTRIES) {
        i2c__STATUS_t status_now = {.w = read_reg(I2C_REG(tgt_idx, STATUS))};

        simputshex32("  ERROR: ACQLVL ", level);
        simputshex32(" != expected entries ", (uint32_t)ACQ_EXPECTED_ENTRIES);
        simputshex32(" (START + ", (uint32_t)ACQ_WRITE_LEN);
        simputshex32(" data + STOP), polls=", polls);
        simputshex32(", target STATUS=", status_now.w);
        simputshex32(", target events=", i2c_get_target_events(tgt_idx));
        simputs("\n");
        if (level == 0) {
            simputs("  [Diagnosis] no entry reached the ACQ FIFO -- the write was NACKed or the\n");
            simputs("              target never matched the address\n");
        }
        return I2C_ERROR_TIMEOUT;
    }

    /* The empty flag with a known non-empty FIFO: the ACQ leg's positive control. */
    i2c__STATUS_t status_filled = {.w = read_reg(I2C_REG(tgt_idx, STATUS))};
    if (status_filled.f.ACQEMPTY) {
        simputshex32("  ERROR: STATUS.ACQEMPTY is set while ACQLVL is ", level);
        simputs("\n");
        return I2C_ERROR;
    }
    if (status_filled.f.ACQFULL) {
        simputshex32("  ERROR: STATUS.ACQFULL is set at ACQLVL ", level);
        simputshex32(" of depth ", (uint32_t)I2C_TARGET_RX_FIFO_DEPTH);
        simputs("\n");
        return I2C_ERROR;
    }
    simputs("  PASS: a real write left ACQLVL=");
    simputshex32("", level);
    simputs(" (START + payload + STOP) with ACQEMPTY clear\n");

    /* Both sides must be finished before the reset, for the same reason as the RX
     * leg: with the controller still clocking bytes into the target, "ACQLVL is 0
     * after ACQRST" would be a race against the next entry rather than a property
     * of ACQRST. The AcqStop entry counted above already says the STOP reached
     * the target, so these two waits are short; they also catch a controller that
     * halted instead of completing the transaction. */
    ret = i2c_controller_wait_idle(ctrl_idx, IDLE_POLL_BOUND);
    if (ret != I2C_OK) {
        simputshex32("  ERROR: controller not idle after the write, STATUS=",
                     read_reg(I2C_REG(ctrl_idx, STATUS)));
        simputshex32(", events=", i2c_get_controller_events(ctrl_idx));
        simputs("\n");
        return ret;
    }
    polls = 0;
    while (!i2c_target_is_idle(tgt_idx) && polls < IDLE_POLL_BOUND) {
        polls++;
    }
    if (!i2c_target_is_idle(tgt_idx)) {
        simputshex32("  ERROR: target not idle after the write, STATUS=",
                     read_reg(I2C_REG(tgt_idx, STATUS)));
        simputs("\n");
        return I2C_ERROR_TIMEOUT;
    }
    level = acq_level(tgt_idx);
    if (level != ACQ_EXPECTED_ENTRIES) {
        simputshex32("  ERROR: ACQLVL changed to ", level);
        simputshex32(" while the bus went idle; nothing in this leg pops ACQDATA, expected ",
                     (uint32_t)ACQ_EXPECTED_ENTRIES);
        simputs("\n");
        return I2C_ERROR;
    }

    // The reset under test, applied to a FIFO that is provably non-empty
    i2c_reset_fifos(tgt_idx, false, false, false, true);
    ret = check_reset_took(g_i2c_acq_reset_needed_drain, g_i2c_acq_reset_residual, "ACQRST");
    if (ret != I2C_OK) return ret;

    i2c__STATUS_t status_empty = {.w = read_reg(I2C_REG(tgt_idx, STATUS))};
    if (!status_empty.f.ACQEMPTY) {
        simputs("  ERROR: ACQ FIFO should be empty after reset\n");
        return I2C_ERROR;
    }
    if (status_empty.f.ACQFULL) {
        simputs("  ERROR: ACQ FIFO should not be full after reset\n");
        return I2C_ERROR;
    }
    level = acq_level(tgt_idx);
    if (level != 0) {
        simputshex32("  ERROR: ACQLVL after ACQRST is ", level);
        simputs(" != 0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: ACQRST took the FIFO from ");
    simputshex32("", (uint32_t)ACQ_EXPECTED_ENTRIES);
    simputs(" entries back to ACQLVL=0, ACQEMPTY set\n");
    simputs("  PASS: ACQ FIFO test PASSED\n");
    return I2C_OK;
}

int main(void) {
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C FIFO Fill/Reset Status Test       ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    write_scratch(1, 0x00000011);

    // LEVEL 1 - Wrapper Control Enable (Controller Mode for I2C_0)
    write_scratch(1, 0x00000020);
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    write_scratch(1, 0x00000021);

    // LEVEL 2 - I2C IP Initialization (Controller Mode for I2C_0)
    write_scratch(1, 0x00000030);

    // Compute timing parameters
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

    // Initialize I2C as Controller
    i2c_controller_config_t ctrl_cfg = {
        .timing = computed_timing,
        .fifo = {.rx_thresh = I2C_DEFAULT_RX_THRESH, .fmt_thresh = I2C_DEFAULT_FMT_THRESH},
        .enable_interrupts = false};

    ret = i2c_controller_init(CONTROLLER_IDX, &ctrl_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Controller init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    write_scratch(1, 0x00000031);

    // LEVEL 1 - Wrapper Control Enable (Target Mode for I2C_1)
    write_scratch(1, 0x00000032);
    i2c_wrapper_enable(TARGET_IDX, false);
    write_scratch(1, 0x00000033);

    // LEVEL 2 - I2C IP Initialization (Target Mode for I2C_1)
    write_scratch(1, 0x00000034);

    // Initialize I2C_1 as Target
    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
                                   .mask0 = 0x7F,
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = computed_timing,
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
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00034);
        test_fail(0);
    }
    write_scratch(1, 0x00000035);

    // Explicitly set ACQ_START_STOP_EN via generated field (not hand bit index).
    i2c__CTRL_t ctrl = {.w = read_reg(I2C_REG(TARGET_IDX, CTRL))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(I2C_REG(TARGET_IDX, CTRL), ctrl.w);

    // Distinct setup marker (TB must not race this with final DONE).
    write_scratch(1, 0xEBEDEBE2);

    /* The two bus legs run first, from the post-init state of both instances.
     * The software fill legs after them deliberately leave a FIFO full of
     * entries the FSM never consumes, which is not a state to start a real
     * transfer from. */

    // Test RX FIFO (I2C_0 receives from I2C_1 over the bus)
    write_scratch(1, 0x00000050);
    ret = test_rx_fifo_fill_and_reset(CONTROLLER_IDX, TARGET_IDX);
    if (ret != I2C_OK) {
        simputs("  ERROR: RX FIFO test failed\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }
    write_scratch(1, 0x00000051);

    // Test ACQ FIFO (I2C_1 receives from I2C_0 over the bus)
    write_scratch(1, 0x00000070);
    ret = test_acq_fifo_fill_and_reset(CONTROLLER_IDX, TARGET_IDX);
    if (ret != I2C_OK) {
        simputs("  ERROR: ACQ FIFO test failed\n");
        write_scratch(0, 0xBAD00070);
        test_fail(0);
    }
    write_scratch(1, 0x00000071);

    // Test FMT FIFO (software stores on I2C_0)
    write_scratch(1, 0x00000040);
    ret = test_fmt_fifo_full_empty(CONTROLLER_IDX);
    if (ret != I2C_OK) {
        simputs("  ERROR: FMT FIFO test failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }
    write_scratch(1, 0x00000041);

    // Test TX FIFO (software stores on I2C_1)
    write_scratch(1, 0x00000060);
    ret = test_tx_fifo_full_empty(TARGET_IDX);
    if (ret != I2C_OK) {
        simputs("  ERROR: TX FIFO test failed\n");
        write_scratch(0, 0xBAD00060);
        test_fail(0);
    }
    write_scratch(1, 0x00000061);

    //=========================================================================
    // Test Complete - Signal to testbench
    //=========================================================================
    // Final DONE marker for TB (distinct from setup 0xEBEDEBE2).
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");

    test_pass(0);

    simputs("\n=== Test Complete ===\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
