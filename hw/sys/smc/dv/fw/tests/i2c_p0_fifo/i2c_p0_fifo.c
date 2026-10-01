/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_p0_fifo.c
 * @brief I2C P0 FIFO Threshold Interrupt Test
 *
 * Scope: FIFO *threshold* interrupts on the target-side ACQ and TX FIFOs. This
 * test does not fill any FIFO and does not observe any FULL status bit; the
 * ACQ and TX FIFOs are 64 deep (smc_config_pkg.sv:23-26) and this test peaks at
 * 7 and 5 entries respectively. Fullness, back-pressure at ACQ depth 62
 * (i2c_target_fsm.sv:271) and the silent FDATA drop (i2c_core.sv:379) are out
 * of scope here.
 *
 * RX (ACQ) leg -- the target receives, an external VIP master drives:
 *   1. Arm *before* the testbench is released: program ACQ_THRESH = N, enable
 *      INTR_ENABLE.ACQ_THRESHOLD, and assert the observer's starting state --
 *      ACQ empty, no manual drain needed by the setup FIFO reset, and
 *      INTR_STATE.ACQ_THRESHOLD deasserted at level 0.
 *   2. Release the VIP, then poll. Prove both directions of the RTL boundary
 *      (acq_gt_threshold = acq_fifo_depth > ACQ_THRESH, i2c_core.sv:370, into
 *      INTR_STATE.ACQ_THRESHOLD at :986/:1010):
 *        - a sample at ACQLVL == N with the interrupt deasserted, and
 *        - the interrupt asserted only at ACQLVL > N.
 *   3. Assert the *entry* count exactly: with ACQ_START_STOP_EN set the FSM
 *      pushes an AcqStart entry (i2c_target_fsm.sv:434) and an AcqStop entry
 *      (:644) around the payload, so 5 data bytes produce 7 entries -- and the
 *      interrupt therefore fires on the 5th data byte (level 6), not on the
 *      Nth byte of payload.
 *   4. Read ACQDATA back and check the framing and the payload the VIP wrote.
 *
 * TX leg -- the target transmits, no external reader, so the level is driven by
 * software stores and by TXRST:
 *   1. After TXRST, assert TXLVL == 0 exactly and the interrupt asserted.
 *   2. Write M-1 bytes, assert TXLVL == M-1 exactly, interrupt still asserted.
 *   3. Write the Mth byte, assert TXLVL == M exactly, interrupt deasserted --
 *      the upward crossing of tx_lt_threshold (i2c_core.sv:368).
 *   4. TXRST again, assert TXLVL == 0 and the interrupt re-asserted -- the
 *      downward crossing.
 *   Every expected level is the number of bytes this test stored, not a value
 *   read back from the DUT, so a TXDATA path that dropped its stores fails here
 *   instead of passing on TXLVL == 0.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_io.h"
#include "smc_test.h"
#include "i2c_opentitan.h"

// Test parameters
#define TARGET_IDX 0
#define TARGET_ADDR 0x10
#define RX_FIFO_THRESHOLD_N 5 // ACQ FIFO threshold for RX test
#define TX_FIFO_THRESHOLD_M 5 // TX FIFO threshold for TX test

/* The stimulus the testbench drives, mirrored here so the expectations below
 * are stated against it rather than against anything read from the DUT.
 * Source: tb_wrap_cocotb/tests/smc_i2c_p0_fifo.py:100-101 (5 bytes, 0xAA..0xAE,
 * written to target address 0x10) -- keep the two in step. */
#define RX_BYTE_COUNT 5
#define RX_FIRST_DATA_BYTE 0xAAu
/* START entry + payload + STOP entry (ACQ_START_STOP_EN is set in main). */
#define RX_EXPECTED_ACQ_ENTRIES (1u + RX_BYTE_COUNT + 1u)
/* The AcqStart entry carries the address byte the FSM shifted in, i.e. the
 * 7-bit address with the R/W bit appended (i2c_target_fsm.sv:434). */
#define RX_START_ACQ_BYTE ((TARGET_ADDR << 1) | 0u)

/* One accessor for every register in this file. The per-instance stride is the
 * same 0x200 in SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR() and in every per-register
 * macro (smc_addr.h:54,631...), so indexing the register macro directly is both
 * shorter and correct for idx != 0, unlike a base-plus-offset(0) expression. */
#define I2C_REG(idx, REG) (SMC_TOP_SMC_I2C_WRAP_I2C_##REG##_BASE_ADDR(idx))

/* Poll bounds, in loop iterations.
 *
 * Sized from measured cost, not guessed, at the corner the bench can draw. A
 * single-register poll iteration costs 0.23 us at the 4 ns core clock the bench
 * can pick (measured in i2c_fifo_full) and ~0.34 us at 6 ns; the loops below
 * read two registers per pass, so ~0.46-0.68 us each.
 *
 * The longest legitimate wait in this test is the VIP's 5-byte write at 100 kHz,
 * which took 1.10 ms in the reference run (1783040 ns -> 2888040 ns) and takes
 * up to 1.5x that when the bench draws the 12 ns peripheral clock. The
 * outermost bound in the stack is the testbench's 20 ms completion wait
 * (tb_wrap_cocotb/tests/smc_i2c_p0_fifo.py). Every bound here must therefore
 * expire well inside 20 ms, or its failure branch is unreachable code and the
 * diagnostics behind it can never print.
 *
 *  12000 iterations ~= 5.5-8.2 ms : 3.3x the 1.65 ms worst-corner transaction,
 *                                   under 20 ms.
 *   6000 iterations ~= 2.8-4.1 ms : the STOP entry lands about one byte period
 *                                   (90-135 us) after the last data byte.
 *    500 iterations ~= 0.23-0.34 ms: a TXDATA store reaches TXLVL in a few cycles.
 */
#define RX_INTR_POLL_BOUND 12000u
#define RX_ENTRIES_POLL_BOUND 6000u
#define TX_LEVEL_POLL_BOUND 500u

/**
 * @brief Enable I2C Wrapper Control (LEVEL 1)
 */
static void i2c_wrapper_enable(uint32_t idx, bool controller_mode) {
    uint32_t wrapper_addr = SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(idx);

    i2c_ctrl__I2C_CTRL_t ctrl = {.w = 0};
    ctrl.f.I2C_EN = 1;
    ctrl.f.I2C_CONTROLLER_MODE_EN = controller_mode ? 1 : 0;

    write_reg(wrapper_addr, ctrl.w);

    simputs("  Wrapper[");
    simputshex32("", idx);
    simputs("] enabled: mode=");
    simputs(controller_mode ? "Controller" : "Target");
    simputs("\n");
}

/**
 * @brief Arm the RX (ACQ) threshold observation.
 *
 * Runs before the firmware publishes its ready marker, so the whole VIP
 * transaction happens inside the observed window. Every state this leg depends
 * on is asserted here rather than printed.
 */
static int rx_arm(uint32_t idx, uint32_t threshold_n) {
    simputs("\n=== RX (ACQ) FIFO threshold: arm ===\n");

    // Configure ACQ FIFO threshold
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_CONFIG))};
    fifo_cfg.f.ACQ_THRESH = threshold_n;
    write_reg(I2C_REG(idx, TARGET_FIFO_CONFIG), fifo_cfg.w);

    i2c__TARGET_FIFO_CONFIG_t fifo_cfg_rb = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_CONFIG))};
    if ((uint32_t)fifo_cfg_rb.f.ACQ_THRESH != threshold_n) {
        simputs("  ERROR: ACQ_THRESH readback ");
        simputshex32("", fifo_cfg_rb.f.ACQ_THRESH);
        simputs(" != programmed ");
        simputshex32("", threshold_n);
        simputs("\n");
        return I2C_ERROR;
    }

    // Enable the ACQ threshold interrupt, then clear INTR_STATE
    i2c__INTR_ENABLE_t intr_en = {.w = read_reg(I2C_REG(idx, INTR_ENABLE))};
    intr_en.f.ACQ_THRESHOLD = 1;
    write_reg(I2C_REG(idx, INTR_ENABLE), intr_en.w);

    i2c__INTR_ENABLE_t intr_en_rb = {.w = read_reg(I2C_REG(idx, INTR_ENABLE))};
    if (!intr_en_rb.f.ACQ_THRESHOLD) {
        simputs("  ERROR: INTR_ENABLE.ACQ_THRESHOLD did not set\n");
        return I2C_ERROR;
    }
    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    /* Starting state of the observer. Nothing is on the bus yet -- the ready
     * marker has not been published -- so all of these are checkable facts, not
     * races. */
    i2c__CTRL_t ctrl = {.w = read_reg(I2C_REG(idx, CTRL))};
    if (!ctrl.f.ENABLETARGET) {
        simputs("  ERROR: CTRL.ENABLETARGET is 0 -- target will not answer the VIP\n");
        return I2C_ERROR;
    }
    if (!ctrl.f.ACQ_START_STOP_EN) {
        simputs("  ERROR: CTRL.ACQ_START_STOP_EN is 0 -- START/STOP entries expected below\n");
        return I2C_ERROR;
    }

    i2c__TARGET_ID_t target_id = {.w = read_reg(I2C_REG(idx, TARGET_ID))};
    if ((uint32_t)target_id.f.ADDRESS0 != (uint32_t)TARGET_ADDR) {
        simputs("  ERROR: TARGET_ID.ADDRESS0 ");
        simputshex32("", target_id.f.ADDRESS0);
        simputs(" != ");
        simputshex32("", TARGET_ADDR);
        simputs("\n");
        return I2C_ERROR;
    }

    i2c__STATUS_t status = {.w = read_reg(I2C_REG(idx, STATUS))};
    if (!status.f.TARGETIDLE) {
        simputs("  ERROR: STATUS.TARGETIDLE is 0 before any bus activity\n");
        return I2C_ERROR;
    }
    if (!status.f.ACQEMPTY) {
        simputs("  ERROR: STATUS.ACQEMPTY is 0 before any bus activity\n");
        return I2C_ERROR;
    }

    /* "The ACQ FIFO started empty" is a precondition of everything below, so it
     * is established rather than assumed. i2c_reset_fifos() records whether the
     * hardware ACQRST actually took or whether the helper had to drain the FIFO
     * by hand; reading the flag is the only way to tell those apart, because in
     * both cases the level ends up 0. */
    if (g_i2c_acq_reset_needed_drain) {
        simputs("  ERROR: setup ACQRST did not take -- the helper drained the ACQ FIFO by hand\n");
        return I2C_ERROR;
    }

    i2c__TARGET_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};
    if (fifo_status.f.ACQLVL != 0) {
        simputs("  ERROR: ACQLVL ");
        simputshex32("", fifo_status.f.ACQLVL);
        simputs(" != 0 before the VIP write\n");
        return I2C_ERROR;
    }

    /* Level 0 is not > threshold, so the interrupt must be deasserted here.
     * This is the negative half of the boundary, taken from a known state. */
    i2c__INTR_STATE_t intr_state = {.w = read_reg(I2C_REG(idx, INTR_STATE))};
    if (intr_state.f.ACQ_THRESHOLD) {
        simputs("  ERROR: INTR_STATE.ACQ_THRESHOLD asserted at ACQLVL=0, threshold ");
        simputshex32("", threshold_n);
        simputs("\n");
        return I2C_ERROR;
    }

    simputs("  PASS: armed at ACQLVL=0, ACQ_THRESH=");
    simputshex32("", threshold_n);
    simputs(", ACQ_THRESHOLD deasserted, hardware ACQRST took\n");
    return I2C_OK;
}

/**
 * @brief Observe the RX (ACQ) threshold crossing and check what produced it.
 */
static int rx_observe(uint32_t idx, uint32_t threshold_n) {
    uint32_t count = 0;
    uint32_t lvl_at_intr = 0;
    uint32_t max_lvl_without_intr = 0;
    bool intr_seen = false;
    bool boundary_seen = false;

    simputs("\n=== RX (ACQ) FIFO threshold: observe ===\n");

    while (count < RX_INTR_POLL_BOUND) {
        /* Read the level FIRST and the interrupt SECOND.
         *
         * Nothing in this leg pops ACQDATA, so acq_fifo_depth is monotonically
         * non-decreasing across the whole loop. With this ordering,
         * ACQLVL(t1) > threshold implies depth(t2) >= ACQLVL(t1) > threshold at
         * the later INTR_STATE sample, so "level above threshold with the
         * interrupt deasserted" is a real RTL violation and not a read-skew
         * artifact. INTR_STATE.ACQ_THRESHOLD tracks acq_gt_threshold
         * combinationally (i2c_core.sv:370 -> :986 -> :1010). */
        i2c__TARGET_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};
        i2c__INTR_STATE_t intr_state = {.w = read_reg(I2C_REG(idx, INTR_STATE))};

        if (intr_state.f.ACQ_THRESHOLD) {
            /* Re-read the level after the interrupt sample. The depth can only
             * have grown since, so a level <= threshold here means the DUT
             * asserted the interrupt below its threshold. That is a failure,
             * not a warning to keep spinning on. */
            i2c__TARGET_FIFO_STATUS_t fifo_after = {.w =
                                                        read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};
            if ((uint32_t)fifo_after.f.ACQLVL <= threshold_n) {
                simputs("  ERROR: ACQ_THRESHOLD asserted at ACQLVL ");
                simputshex32("", fifo_after.f.ACQLVL);
                simputs(" <= threshold ");
                simputshex32("", threshold_n);
                simputs(" (level at the interrupt sample was ");
                simputshex32("", fifo_status.f.ACQLVL);
                simputs(", INTR_STATE=");
                simputshex32("", intr_state.w);
                simputs(") -- i2c_core.sv:370 requires ACQLVL > ACQ_THRESH\n");
                return I2C_ERROR;
            }
            lvl_at_intr = fifo_after.f.ACQLVL;
            intr_seen = true;
            break;
        }

        if ((uint32_t)fifo_status.f.ACQLVL > threshold_n) {
            simputs("  ERROR: ACQLVL ");
            simputshex32("", fifo_status.f.ACQLVL);
            simputs(" > threshold ");
            simputshex32("", threshold_n);
            simputs(" but ACQ_THRESHOLD is deasserted (INTR_STATE=");
            simputshex32("", intr_state.w);
            simputs(")\n");
            return I2C_ERROR;
        }

        if ((uint32_t)fifo_status.f.ACQLVL == threshold_n) {
            boundary_seen = true;
        }
        if ((uint32_t)fifo_status.f.ACQLVL > max_lvl_without_intr) {
            max_lvl_without_intr = fifo_status.f.ACQLVL;
        }
        count++;
    }

    if (!intr_seen) {
        i2c__TARGET_FIFO_STATUS_t fifo_final = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};
        i2c__STATUS_t status_final = {.w = read_reg(I2C_REG(idx, STATUS))};
        i2c__INTR_STATE_t intr_final = {.w = read_reg(I2C_REG(idx, INTR_STATE))};
        i2c__INTR_ENABLE_t en_final = {.w = read_reg(I2C_REG(idx, INTR_ENABLE))};

        simputs("  ERROR: ACQ_THRESHOLD did not assert within the poll bound\n");
        simputs("  polls=");
        simputshex32("", count);
        simputs(" bound=");
        simputshex32("", (uint32_t)RX_INTR_POLL_BOUND);
        simputs("\n  ACQLVL=");
        simputshex32("", fifo_final.f.ACQLVL);
        simputs(" max ACQLVL seen=");
        simputshex32("", max_lvl_without_intr);
        simputs(" threshold=");
        simputshex32("", threshold_n);
        simputs("\n  TARGETIDLE=");
        simputshex32("", status_final.f.TARGETIDLE ? 1 : 0);
        simputs(" ACQEMPTY=");
        simputshex32("", status_final.f.ACQEMPTY ? 1 : 0);
        simputs(" INTR_STATE=");
        simputshex32("", intr_final.w);
        simputs(" INTR_ENABLE.ACQ_THRESHOLD=");
        simputshex32("", en_final.f.ACQ_THRESHOLD ? 1 : 0);
        simputs("\n");

        if (max_lvl_without_intr == 0) {
            simputs("  [Diagnosis] no entry ever reached the ACQ FIFO -- the VIP transaction "
                    "was NACKed or never addressed this target\n");
        } else {
            simputs("  [Diagnosis] the ACQ FIFO filled but never rose above the threshold\n");
        }
        return I2C_ERROR_TIMEOUT;
    }

    /* The negative half of the boundary, observed on the way up. Each ACQ level
     * persists for a byte period (90 us at 100 kHz) against a poll of a couple
     * of microseconds, so missing it means the observer was armed late. */
    if (!boundary_seen) {
        simputs("  ERROR: never sampled ACQLVL == threshold (");
        simputshex32("", threshold_n);
        simputs(") with the interrupt deasserted; highest level seen without the interrupt was ");
        simputshex32("", max_lvl_without_intr);
        simputs(", interrupt first seen at ACQLVL ");
        simputshex32("", lvl_at_intr);
        simputs(" -- the threshold crossing was outside the observed window\n");
        return I2C_ERROR;
    }

    simputs("  PASS: ACQLVL == threshold (");
    simputshex32("", threshold_n);
    simputs(") observed with ACQ_THRESHOLD deasserted\n");
    simputs("  PASS: ACQ_THRESHOLD asserted at ACQLVL ");
    simputshex32("", lvl_at_intr);
    simputs(" > threshold ");
    simputshex32("", threshold_n);
    simputs("\n");

    /* Let the transaction finish, then state the expectation in ACQ entries:
     * START + RX_BYTE_COUNT data + STOP. */
    uint32_t settle = 0;
    i2c__TARGET_FIFO_STATUS_t fifo_entries = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};
    while ((uint32_t)fifo_entries.f.ACQLVL < RX_EXPECTED_ACQ_ENTRIES &&
           settle < RX_ENTRIES_POLL_BOUND) {
        fifo_entries.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS));
        settle++;
    }
    if ((uint32_t)fifo_entries.f.ACQLVL != RX_EXPECTED_ACQ_ENTRIES) {
        simputs("  ERROR: final ACQLVL ");
        simputshex32("", fifo_entries.f.ACQLVL);
        simputs(" != expected entries ");
        simputshex32("", (uint32_t)RX_EXPECTED_ACQ_ENTRIES);
        simputs(" (START + ");
        simputshex32("", (uint32_t)RX_BYTE_COUNT);
        simputs(" data + STOP), polls=");
        simputshex32("", settle);
        simputs("\n");
        return I2C_ERROR;
    }
    simputs("  PASS: final ACQLVL == ");
    simputshex32("", (uint32_t)RX_EXPECTED_ACQ_ENTRIES);
    simputs(" entries\n");

    /* Read the entries back and check that they are the ones the VIP wrote.
     * Without this the level alone cannot be attributed to the stimulus. */
    for (uint32_t i = 0; i < RX_EXPECTED_ACQ_ENTRIES; i++) {
        i2c__ACQDATA_t entry = {.w = read_reg(I2C_REG(idx, ACQDATA))};
        uint32_t expected_signal;
        uint32_t expected_byte;
        bool check_byte = true;

        if (i == 0) {
            expected_signal = I2C_ACQ_SIGNAL_START;
            expected_byte = RX_START_ACQ_BYTE;
        } else if (i <= (uint32_t)RX_BYTE_COUNT) {
            expected_signal = I2C_ACQ_SIGNAL_DATA;
            expected_byte = (RX_FIRST_DATA_BYTE + (i - 1)) & 0xFFu;
        } else {
            /* The AcqStop entry carries whatever byte was last shifted in
             * (i2c_target_fsm.sv:644 writes {AcqStop, input_byte}), so only the
             * signal field is specified. */
            expected_signal = I2C_ACQ_SIGNAL_STOP;
            expected_byte = 0;
            check_byte = false;
        }

        if ((uint32_t)entry.f.SIGNAL != expected_signal) {
            simputs("  ERROR: ACQ entry ");
            simputshex32("", i);
            simputs(" SIGNAL ");
            simputshex32("", entry.f.SIGNAL);
            simputs(" != expected ");
            simputshex32("", expected_signal);
            simputs(" (ABYTE=");
            simputshex32("", entry.f.ABYTE);
            simputs(")\n");
            return I2C_ERROR;
        }
        if (check_byte && (uint32_t)entry.f.ABYTE != expected_byte) {
            simputs("  ERROR: ACQ entry ");
            simputshex32("", i);
            simputs(" ABYTE ");
            simputshex32("", entry.f.ABYTE);
            simputs(" != expected ");
            simputshex32("", expected_byte);
            simputs("\n");
            return I2C_ERROR;
        }
    }
    simputs("  PASS: ACQ entries are START(");
    simputshex32("", (uint32_t)RX_START_ACQ_BYTE);
    simputs(") + ");
    simputshex32("", (uint32_t)RX_BYTE_COUNT);
    simputs(" data bytes from ");
    simputshex32("", (uint32_t)RX_FIRST_DATA_BYTE);
    simputs(" + STOP\n");

    /* Draining all the entries must take the level back to 0 and the interrupt
     * with it -- the third crossing of the boundary, downwards. */
    i2c__TARGET_FIFO_STATUS_t fifo_drained = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};
    if (fifo_drained.f.ACQLVL != 0) {
        simputs("  ERROR: ACQLVL ");
        simputshex32("", fifo_drained.f.ACQLVL);
        simputs(" != 0 after reading back every entry\n");
        return I2C_ERROR;
    }
    i2c__INTR_STATE_t intr_drained = {.w = read_reg(I2C_REG(idx, INTR_STATE))};
    if (intr_drained.f.ACQ_THRESHOLD) {
        simputs("  ERROR: ACQ_THRESHOLD still asserted at ACQLVL=0\n");
        return I2C_ERROR;
    }
    simputs("  PASS: ACQ_THRESHOLD deasserted again once the FIFO is drained\n");

    i2c_clear_interrupts(idx, 0xFFFFFFFF);
    simputs("  RX FIFO threshold test PASSED\n");
    return I2C_OK;
}

/**
 * @brief Wait for TXLVL to reach an expected level, then check the interrupt.
 *
 * @param expected_level  the number of bytes this test has stored since the
 *                        last TXRST -- a property of the stimulus, never a
 *                        value read back from the DUT
 * @param expect_intr     whether INTR_STATE.TX_THRESHOLD must be asserted at
 *                        that level, i.e. expected_level < TX_THRESH
 */
static int tx_expect_level(uint32_t idx, uint32_t expected_level, bool expect_intr,
                           const char *stage) {
    uint32_t polls = 0;
    i2c__TARGET_FIFO_STATUS_t fifo_status = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS))};

    while ((uint32_t)fifo_status.f.TXLVL != expected_level && polls < TX_LEVEL_POLL_BOUND) {
        fifo_status.w = read_reg(I2C_REG(idx, TARGET_FIFO_STATUS));
        polls++;
    }

    if ((uint32_t)fifo_status.f.TXLVL != expected_level) {
        simputs("  ERROR: ");
        simputs(stage);
        simputs(": TXLVL ");
        simputshex32("", fifo_status.f.TXLVL);
        simputs(" != expected ");
        simputshex32("", expected_level);
        simputs(" after ");
        simputshex32("", polls);
        simputs(" polls\n");
        return I2C_ERROR;
    }

    i2c__INTR_STATE_t intr_state = {.w = read_reg(I2C_REG(idx, INTR_STATE))};
    bool intr = intr_state.f.TX_THRESHOLD ? true : false;
    if (intr != expect_intr) {
        simputs("  ERROR: ");
        simputs(stage);
        simputs(": TXLVL ");
        simputshex32("", expected_level);
        simputs(" but TX_THRESHOLD is ");
        simputshex32("", intr ? 1 : 0);
        simputs(", expected ");
        simputshex32("", expect_intr ? 1 : 0);
        simputs(" (INTR_STATE=");
        simputshex32("", intr_state.w);
        simputs(")\n");
        return I2C_ERROR;
    }

    simputs("  PASS: ");
    simputs(stage);
    simputs(": TXLVL == ");
    simputshex32("", expected_level);
    simputs(", TX_THRESHOLD == ");
    simputshex32("", expect_intr ? 1 : 0);
    simputs("\n");
    return I2C_OK;
}

/**
 * @brief Test the TX FIFO threshold interrupt.
 *
 * tx_lt_threshold = tx_fifo_depth < TX_THRESH (i2c_core.sv:368) feeds
 * INTR_STATE.TX_THRESHOLD (:992-993, :1019), so the interrupt is asserted while
 * the FIFO holds fewer than TX_THRESH bytes.
 */
static int test_tx_fifo_threshold(uint32_t idx, uint32_t threshold_m) {
    uint8_t test_data[32];
    uint32_t i;
    int ret;

    simputs("\n=== Test TX FIFO Threshold ===\n");
    simputs("  TX_THRESH = ");
    simputshex32("", threshold_m);
    simputs(" (interrupt asserted while TXLVL < TX_THRESH)\n");

    for (i = 0; i < 32; i++) {
        test_data[i] = (uint8_t)(0xAA + i);
    }

    // Configure TX FIFO threshold
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_CONFIG))};
    fifo_cfg.f.TX_THRESH = threshold_m;
    write_reg(I2C_REG(idx, TARGET_FIFO_CONFIG), fifo_cfg.w);

    i2c__TARGET_FIFO_CONFIG_t fifo_cfg_rb = {.w = read_reg(I2C_REG(idx, TARGET_FIFO_CONFIG))};
    if ((uint32_t)fifo_cfg_rb.f.TX_THRESH != threshold_m) {
        simputs("  ERROR: TX_THRESH readback ");
        simputshex32("", fifo_cfg_rb.f.TX_THRESH);
        simputs(" != programmed ");
        simputshex32("", threshold_m);
        simputs("\n");
        return I2C_ERROR;
    }

    // Enable the TX threshold interrupt
    i2c__INTR_ENABLE_t intr_en = {.w = read_reg(I2C_REG(idx, INTR_ENABLE))};
    intr_en.f.TX_THRESHOLD = 1;
    write_reg(I2C_REG(idx, INTR_ENABLE), intr_en.w);

    i2c__INTR_ENABLE_t intr_en_rb = {.w = read_reg(I2C_REG(idx, INTR_ENABLE))};
    if (!intr_en_rb.f.TX_THRESHOLD) {
        simputs("  ERROR: INTR_ENABLE.TX_THRESHOLD did not set\n");
        return I2C_ERROR;
    }
    i2c_clear_interrupts(idx, 0xFFFFFFFF);

    /* Step 0: reset the TX FIFO. TXLVL == 0 is asserted, not assumed -- it is
     * the anchor every later level is counted from. */
    i2c_reset_fifos(idx, false, false, true, false);
    ret = tx_expect_level(idx, 0, true, "after TXRST"); /* 0 < TX_THRESH */
    if (ret != I2C_OK) return ret;

    /* Step 1: store M-1 bytes. The expected level is the store count. */
    simputs("  Writing ");
    simputshex32("", threshold_m - 1);
    simputs(" bytes into TXDATA\n");
    for (i = 0; i < threshold_m - 1; i++) {
        i2c__TXDATA_t txdata = {.w = 0};
        txdata.f.DATA = test_data[i];
        write_reg(I2C_REG(idx, TXDATA), txdata.w);
    }
    ret = tx_expect_level(idx, threshold_m - 1, true, "after M-1 stores"); /* M-1 < M */
    if (ret != I2C_OK) return ret;

    /* Step 2: the Mth store crosses the boundary upwards. */
    simputs("  Writing the Mth byte into TXDATA\n");
    i2c__TXDATA_t txdata = {.w = 0};
    txdata.f.DATA = test_data[threshold_m - 1];
    write_reg(I2C_REG(idx, TXDATA), txdata.w);

    ret = tx_expect_level(idx, threshold_m, false, "after M stores"); /* M is not < M */
    if (ret != I2C_OK) return ret;

    /* Step 3: cross the boundary downwards. No external controller reads this
     * target in this test, so TXRST is the only way to lower the level; what
     * matters is that the interrupt follows the level back across the
     * threshold rather than only being sampled in one steady state. */
    simputs("  Resetting the TX FIFO from level M\n");
    i2c_reset_fifos(idx, false, false, true, false);
    ret = tx_expect_level(idx, 0, true, "after TXRST from level M");
    if (ret != I2C_OK) return ret;

    i2c_clear_interrupts(idx, 0xFFFFFFFF);
    simputs("  TX FIFO threshold test PASSED\n");
    return I2C_OK;
}

int main(void) {
    int ret;

    simputs("\n");
    simputs("################################################\n");
    simputs("##      I2C P0 FIFO Threshold Test          ##\n");
    simputs("################################################\n");
    simputs("\n");

    write_scratch(1, 0x00000010);
    simputs("Step 1: System Initialization\n");
    simputs("  System ready\n");
    write_scratch(1, 0x00000011);

    // LEVEL 1 - Wrapper Control Enable
    write_scratch(1, 0x00000020);
    simputs("\nStep 2: LEVEL 1 - Wrapper Control Enable\n");
    i2c_wrapper_enable(TARGET_IDX, false); // Target mode
    write_scratch(1, 0x00000021);

    // LEVEL 2 - I2C IP Initialization
    write_scratch(1, 0x00000030);
    simputs("\nStep 3: LEVEL 2 - I2C IP Initialization\n");
    simputs("  Initializing I2C_0 as Target (addr=0x10)...\n");

    // Compute timing parameters
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

    // Initialize I2C as Target
    i2c_target_config_t tgt_cfg = {.address0 = TARGET_ADDR,
                                   .mask0 = 0x7F,
                                   .address1 = 0,
                                   .mask1 = 0,
                                   .timing = computed_timing,
                                   .fifo = {.tx_thresh = TX_FIFO_THRESHOLD_M,
                                            .acq_thresh = RX_FIFO_THRESHOLD_N,
                                            .rx_thresh = 0,
                                            .fmt_thresh = 0},
                                   .enable_interrupts = false, // We'll enable interrupts manually
                                   .ack_ctrl_mode = false,
                                   .tx_stretch_ctrl = false,
                                   .timeout_cycles = 0};

    ret = i2c_target_init(TARGET_IDX, &tgt_cfg);
    if (ret != I2C_OK) {
        simputs("  ERROR: Target init failed\n");
        write_scratch(0, 0xBAD00030);
        test_fail(0);
    }
    simputs("  Target initialized successfully\n");

    /* i2c_target_init() resets the ACQ and TX FIFOs. Whether the hardware reset
     * took, or whether the helper had to repair the FIFO in software, is the
     * difference between "the ACQ FIFO started empty" being a DUT property and
     * being an artifact of the setup path -- and the level alone cannot tell
     * them apart, so the flag is read here, immediately after the only call
     * that can set it. */
    if (g_i2c_acq_reset_needed_drain) {
        simputs("  ERROR: setup ACQRST did not take -- ACQ FIFO was drained in software\n");
        write_scratch(0, 0xBAD00031);
        test_fail(0);
    }
    write_scratch(1, 0x00000031);

    // Explicitly set ACQ_START_STOP_EN bit to 1
    i2c__CTRL_t ctrl = {.w = read_reg(I2C_REG(TARGET_IDX, CTRL))};
    ctrl.f.ACQ_START_STOP_EN = 1;
    write_reg(I2C_REG(TARGET_IDX, CTRL), ctrl.w);

    /* Arm the RX observation BEFORE publishing the ready marker. The testbench
     * starts the VIP write the moment it sees the marker, so anything armed
     * after it races the stimulus it is supposed to observe. */
    write_scratch(1, 0x00000040);
    ret = rx_arm(TARGET_IDX, RX_FIFO_THRESHOLD_N);
    if (ret != I2C_OK) {
        simputs("  ERROR: RX FIFO threshold arm failed\n");
        write_scratch(0, 0xBAD00040);
        test_fail(0);
    }

    // Signal setup complete to testbench -- the VIP write starts here
    write_scratch(1, 0xEBEDEBE4);
    simputs("\n  Firmware armed, releasing testbench VIP...\n");

    ret = rx_observe(TARGET_IDX, RX_FIFO_THRESHOLD_N);
    if (ret != I2C_OK) {
        simputs("  ERROR: RX FIFO threshold test failed\n");
        write_scratch(0, 0xBAD00041);
        test_fail(0);
    }
    write_scratch(1, 0x00000041);

    // Test TX FIFO threshold
    write_scratch(1, 0x00000050);
    ret = test_tx_fifo_threshold(TARGET_IDX, TX_FIFO_THRESHOLD_M);
    if (ret != I2C_OK) {
        simputs("  ERROR: TX FIFO threshold test failed\n");
        write_scratch(0, 0xBAD00050);
        test_fail(0);
    }
    write_scratch(1, 0x00000051);

    // Test Complete
    write_scratch(1, 0x00000090);
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
