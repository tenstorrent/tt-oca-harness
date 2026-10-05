/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief I2C FIFO Fill/Reset Test - Controller and Target FIFOs
 *
 * Verifies fill and reset of the four FIFOs of an I2C pair, with I2C_0 as
 * controller and I2C_1 as target on the same bus. The FMT and TX FIFOs are
 * filled by software stores until they report full, and both the level and the
 * store count must equal the configured depth. The RX and ACQ FIFOs are filled
 * by a real bus transfer to an exact level below full, because only the bus can
 * put entries in them. Each reset must empty its FIFO without the driver's
 * software repair, which could otherwise produce the empty level by itself.
 * RX full and ACQ full are not covered; ACQ full is covered by
 * i2c_acq_fifo_stretch_reset.
 *
 * Each leg publishes its own progress marker and failure code, distinct from
 * the markers the shared I2C driver can publish, so a hang identifies the FIFO
 * under test rather than the execution order.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

#define CONTROLLER_IDX 0 // I2C_0 for Controller mode (FMT, RX FIFO)
#define TARGET_IDX 1     // I2C_1 for Target mode (TX, ACQ FIFO)
#define TARGET_ADDR 0x10 // 7-bit target address programmed into I2C_1

#define FMT_FIFO_DEPTH I2C_CONTROLLER_TX_FIFO_DEPTH
#define TX_FIFO_DEPTH I2C_TARGET_TX_FIFO_DEPTH

/* Transfer lengths for the two FIFOs that only the bus can fill; both stay
 * below the FIFO depth. */
#define RX_READ_LEN 8u
#define ACQ_WRITE_LEN 8u
/* With start/stop capture enabled, the target adds a start entry (carrying the
 * address) and a stop entry around the payload. */
#define ACQ_EXPECTED_ENTRIES (1u + ACQ_WRITE_LEN + 1u)

/* Address of an I2C register of instance idx, from the generated macros. */
#define I2C_REG(idx, REG) (SMC_TOP_SMC_I2C_WRAP_I2C_##REG##_BASE_ADDR(idx))

/* Poll bounds in loop iterations. They cover the longest standard-mode
 * transfer in this test with margin and expire before the testbench's
 * completion timeout, so the diagnostics behind them can print.
 * I2C_TIMEOUT_DEFAULT is too long for that. */
#define XFER_POLL_BOUND 16000u
#define IDLE_POLL_BOUND 16000u

/**
 * @brief Enable the I2C wrapper in controller or target mode
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

/* Fail a leg when i2c_reset_fifos() had to repair the FIFO in software, because
 * then an empty level after the reset does not show that the hardware reset
 * worked. The driver also fails closed by default; this check keeps each leg
 * correct if the repair gate is opened. */
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
 * The controller is disabled for the duration, so software stores are the only
 * producer and every level checked here is the store count. The controller is
 * left disabled on return; no later leg uses it.
 */
static int test_fmt_fifo_full_empty(uint32_t idx) {
    uint32_t pushed = 0;
    uint32_t level;
    bool full_seen = false;
    int ret;

    simputs("\n=== Test FMT FIFO Full/Empty ===\n");

    /* The filler entries are never transmitted, so this leg must not start
     * while an earlier transaction is still in flight. */
    if (!i2c_controller_is_idle(idx)) {
        simputs("  ERROR: controller not idle before the FMT fill\n");
        return I2C_ERROR;
    }

    /* An enabled controller starts transmitting as soon as the FMT FIFO is
     * non-empty and the bus is free, and would pop entries during the fill.
     * Disabling it does not affect FIFO writes, the full flag or the FIFO
     * reset. */
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

    /* Check the full flag before each store, because a store into a full FIFO
     * is dropped silently. The loop cap is a little above the configured depth,
     * so a deeper FIFO never reports full and the leg fails. */
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

    /* The store count and the DUT's level are independent checks; the full flag
     * alone does not show that the FIFO filled to the configured depth. */
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
 * Both FMT entries are written back to back, as i2c_controller_read() does,
 * because the controller returns to idle if the read entry is not queued
 * behind the address entry before the first one is popped. Unlike
 * i2c_controller_read(), this leaves the received bytes in the RX FIFO.
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
 * The target answers a read from its TX FIFO, so the RX entries arrive over the
 * bus, a state the driver's software repair cannot produce.
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
     * read request arrives or it stretches SCL instead of replying. */
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

    /* Clear target events after the preload, not before: filling the TX FIFO
     * can raise an event, and an unhandled one makes the target stretch instead
     * of answering the read request. */
    if (i2c_get_target_events(tgt_idx) != 0) {
        i2c_clear_target_events(tgt_idx, 0xFFFFFFFF);
    }

    /* rx_start_read() needs room for both entries; the FMT FIFO is still empty
     * at this point. */
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

    /* Let the transfer finish before the reset, or an empty level after the
     * reset races the next byte. The level is re-read to show that nothing
     * drained on its own. */
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
 * Same FDATA sequence as i2c_controller_write(), but every wait is bounded by
 * XFER_POLL_BOUND instead of the driver's much longer default timeout, so a
 * stuck transfer reports a FIFO-level diagnostic before the testbench times
 * out. The full flag is checked before each store because a store into a full
 * FMT FIFO is dropped silently and would shorten the payload.
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
 * The controller writes a known number of bytes to the target, so the ACQ
 * entries arrive over the bus, a state the driver's software drain cannot
 * produce.
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

    /* Anchor: the RX leg leaves its own entries in the ACQ FIFO, so this reset
     * makes the entry count below attributable to the write alone. */
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
        simputs("         ACQ_START and ACQ_STOP entries are pushed\n");
        return I2C_ERROR;
    }

    /* The FMT FIFO must be able to hold the whole write; it is still empty at
     * this point. */
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

    /* The expected entry count comes from the stimulus, not from the DUT. */
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

    /* Both sides must be idle before the reset, for the same reason as in the RX
     * leg. The waits also catch a controller that halted instead of completing
     * the transaction. */
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

    // Initialize I2C_0 as controller
    write_scratch(1, 0x00000020);
    i2c_wrapper_enable(CONTROLLER_IDX, true);
    write_scratch(1, 0x00000021);

    write_scratch(1, 0x00000030);

    i2c_timing_physical_t physical_params = {.speed = I2C_SPEED_STANDARD,
                                             .clock_period_nanos = 5,
                                             .sda_rise_nanos = 300,
                                             .sda_fall_nanos = 100,
                                             .scl_period_nanos = 0};

    i2c_timing_config_t computed_timing;
    ret = i2c_compute_timing_from_physical(&physical_params, &computed_timing);
    if (ret != I2C_OK) {
        simputs("  WARNING: Physical timing computation failed, using defaults\n");
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &computed_timing);
    }

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

    // Initialize I2C_1 as target
    write_scratch(1, 0x00000032);
    i2c_wrapper_enable(TARGET_IDX, false);
    write_scratch(1, 0x00000033);

    write_scratch(1, 0x00000034);

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

    // The ACQ leg expects start and stop entries around each write
    i2c__CTRL_t ctrl = {.w = read_reg(I2C_REG(TARGET_IDX, CTRL))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(I2C_REG(TARGET_IDX, CTRL), ctrl.w);

    // Setup-complete marker, distinct from the final done marker
    write_scratch(1, 0xEBEDEBE2);

    /* The two bus legs run first, from the post-init state of both instances.
     * The software fill legs leave a FIFO full of entries that nothing
     * consumes, which is not a state to start a real transfer from. */

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

    // Final done marker for the testbench
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n");
    simputs("################################################\n");
    simputs("##           ALL TESTS PASSED                ##\n");
    simputs("################################################\n");
    simputs("\n");

    test_pass(0);
}
