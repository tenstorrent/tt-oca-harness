/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @file i2c_opentitan.c
 * @brief OpenTitan I2C Driver Implementation
 *
 * Complete I2C driver implementation for OpenTitan I2C IP
 * Based on existing test implementations and OpenTitan specification
 */

#include "i2c_opentitan.h"
#include "smc_io.h"
#include "smc_test.h" /* test_fail() -- i2c_reset_fifos() fails closed on a repair */
#include <string.h>

// ============================================================================
// Internal Helper Functions
// ============================================================================

/**
 * @brief Read register helper
 */
static inline uint32_t i2c_read_reg(uint32_t addr) {
    return read_reg(addr);
}

/**
 * @brief Write register helper
 */
static inline void i2c_write_reg(uint32_t addr, uint32_t value) {
    write_reg(addr, value);
}

/**
 * @brief Round-up integer division helper
 *
 * Performs ceiling division: ceil(a/b).
 * Returns bottom 16 bits of result.
 */
static inline uint16_t round_up_divide(uint32_t a, uint32_t b) {
    if (b == 0) return 0; // Avoid division by zero
    return (uint16_t)(((a - 1) / b) + 1);
}

// ============================================================================
// Basic Functions Implementation
// ============================================================================

uint32_t i2c_get_base(uint32_t idx) {
    return SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0) + (0x200u * idx);
}

void i2c_get_default_timing(uint8_t speed, uint32_t sys_clk_mhz, i2c_timing_config_t *config) {
    if (!config) return;

    // Default values based on i2c_sanity test and specification
    // These values work for most cases
    config->thigh = 0x1A; // SCL high period
    config->tlow = 0x32;  // SCL low period
    config->t_r = 2;      // Rise time
    config->t_f = 2;      // Fall time
    config->tsu_sta = 5;  // START setup time
    config->thd_sta = 4;  // START hold time
    config->tsu_dat = 2;  // Data setup time
    config->thd_dat = 5;  // Data hold time
    config->tsu_sto = 4;  // STOP setup time
    config->t_buf = 5;    // Bus free time

    // Adjust for different speeds if needed
    switch (speed) {
    case I2C_SPEED_STANDARD: // 100 kHz
        // Use defaults
        break;

    case I2C_SPEED_FAST: // 400 kHz
        config->thigh = 0x10;
        config->tlow = 0x20;
        break;

    case I2C_SPEED_FAST_PLUS: // 1 MHz
        config->thigh = 0x08;
        config->tlow = 0x10;
        break;
    }
}

/**
 * @brief Get default timing configuration for specified speed from I2C spec
 *
 * Based on I2C Specification UM10204 Table 10.
 * All timing values are in nanoseconds.
 */
static void get_spec_timing_nanos(uint8_t speed, uint32_t clock_period_nanos,
                                  i2c_timing_config_t *config) {
    // All constants from I2C Specification Table 10
    switch (speed) {
    case I2C_SPEED_STANDARD:                                         // 100 kHz (Standard-mode)
        config->thigh = round_up_divide(4000, clock_period_nanos);   // SCL high: 4.0us
        config->tlow = round_up_divide(4700, clock_period_nanos);    // SCL low: 4.7us
        config->tsu_sta = round_up_divide(4700, clock_period_nanos); // START setup: 4.7us
        config->thd_sta = round_up_divide(4000, clock_period_nanos); // START hold: 4.0us
        config->tsu_dat = round_up_divide(250, clock_period_nanos);  // Data setup: 250ns
        config->thd_dat = 1;                                         // Data hold: 0ns (min 1 cycle)
        config->tsu_sto = round_up_divide(4000, clock_period_nanos); // STOP setup: 4.0us
        config->t_buf = round_up_divide(4700, clock_period_nanos);   // Bus free: 4.7us
        break;

    case I2C_SPEED_FAST:                                            // 400 kHz (Fast-mode)
        config->thigh = round_up_divide(600, clock_period_nanos);   // SCL high: 0.6us
        config->tlow = round_up_divide(1300, clock_period_nanos);   // SCL low: 1.3us
        config->tsu_sta = round_up_divide(600, clock_period_nanos); // START setup: 0.6us
        config->thd_sta = round_up_divide(600, clock_period_nanos); // START hold: 0.6us
        config->tsu_dat = round_up_divide(100, clock_period_nanos); // Data setup: 100ns
        config->thd_dat = 1;                                        // Data hold: 0ns (min 1 cycle)
        config->tsu_sto = round_up_divide(600, clock_period_nanos); // STOP setup: 0.6us
        config->t_buf = round_up_divide(1300, clock_period_nanos);  // Bus free: 1.3us
        break;

    case I2C_SPEED_FAST_PLUS:                                       // 1 MHz (Fast-mode Plus)
        config->thigh = round_up_divide(260, clock_period_nanos);   // SCL high: 0.26us
        config->tlow = round_up_divide(500, clock_period_nanos);    // SCL low: 0.5us
        config->tsu_sta = round_up_divide(260, clock_period_nanos); // START setup: 0.26us
        config->thd_sta = round_up_divide(260, clock_period_nanos); // START hold: 0.26us
        config->tsu_dat = round_up_divide(50, clock_period_nanos);  // Data setup: 50ns
        config->thd_dat = 1;                                        // Data hold: 0ns (min 1 cycle)
        config->tsu_sto = round_up_divide(260, clock_period_nanos); // STOP setup: 0.26us
        config->t_buf = round_up_divide(500, clock_period_nanos);   // Bus free: 0.5us
        break;

    default:
        // Use conservative defaults for unknown speed
        config->thigh = 0x1A;
        config->tlow = 0x32;
        config->t_r = 2;
        config->t_f = 2;
        config->tsu_sta = 5;
        config->thd_sta = 4;
        config->tsu_dat = 2;
        config->thd_dat = 5;
        config->tsu_sto = 4;
        config->t_buf = 5;
        break;
    }
}

int i2c_compute_timing_from_physical(const i2c_timing_physical_t *physical,
                                     i2c_timing_config_t *config) {
    // Parameter validation
    if (!physical || !config) {
        return I2C_ERROR_INVALID;
    }

    if (physical->clock_period_nanos == 0) {
        return I2C_ERROR_INVALID; // Would cause division by zero
    }

    if (physical->speed > I2C_SPEED_FAST_PLUS) {
        return I2C_ERROR_INVALID;
    }

    // Get I2C spec timing for requested speed
    get_spec_timing_nanos(physical->speed, physical->clock_period_nanos, config);

    // Compute rise and fall time from physical parameters
    config->t_r = round_up_divide(physical->sda_rise_nanos, physical->clock_period_nanos);
    config->t_f = round_up_divide(physical->sda_fall_nanos, physical->clock_period_nanos);

    // Get minimum SCL period for requested speed
    const uint32_t kNanosPerKBaud = 1000000; // One million
    uint32_t min_scl_period_nanos;
    switch (physical->speed) {
    case I2C_SPEED_STANDARD:
        min_scl_period_nanos = kNanosPerKBaud / 100; // 10us for 100kHz
        break;
    case I2C_SPEED_FAST:
        min_scl_period_nanos = kNanosPerKBaud / 400; // 2.5us for 400kHz
        break;
    case I2C_SPEED_FAST_PLUS:
        min_scl_period_nanos = kNanosPerKBaud / 1000; // 1us for 1MHz
        break;
    default:
        min_scl_period_nanos = kNanosPerKBaud / 100; // Default to standard
        break;
    }

    // Use user-specified SCL period, or minimum if not specified
    uint32_t scl_period_nanos = physical->scl_period_nanos;
    if (scl_period_nanos < min_scl_period_nanos) {
        scl_period_nanos = min_scl_period_nanos;
    }

    // Convert SCL period to cycles
    uint16_t scl_period_cycles = round_up_divide(scl_period_nanos, physical->clock_period_nanos);

    // Adjust thigh to accommodate the desired SCL period
    // SCL period = thigh + tlow + t_r + t_f
    int32_t lengthened_high_cycles = (int32_t)scl_period_cycles - (int32_t)config->tlow -
                                     (int32_t)config->t_r - (int32_t)config->t_f;

    if (lengthened_high_cycles > (int32_t)config->thigh) {
        if (lengthened_high_cycles < 0 || lengthened_high_cycles > 0xFFFF) {
            return I2C_ERROR_INVALID; // Out of range
        }
        config->thigh = (uint16_t)lengthened_high_cycles;
    }

    // For clock stretching detection to work, SCL high and low time
    // must be at least I2C_MIN_SCL_CYCLES (typically 4) cycles
    if (config->thigh < I2C_MIN_SCL_CYCLES) {
        config->thigh = I2C_MIN_SCL_CYCLES;
    }
    if (config->tlow < I2C_MIN_SCL_CYCLES) {
        config->tlow = I2C_MIN_SCL_CYCLES;
    }

    return I2C_OK;
}

void i2c_config_timing(uint32_t idx, const i2c_timing_config_t *config) {
    if (!config) return;

    uint32_t base = i2c_get_base(idx);

    // TIMING0: SCL periods
    i2c__TIMING0_t timing0 = {.w = 0};
    timing0.f.THIGH = (config->thigh & 0x1FFFu);
    timing0.f.TLOW = (config->tlow & 0x1FFFu);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timing0.w);

    // TIMING1: Rise and fall times
    i2c__TIMING1_t timing1 = {.w = 0};
    timing1.f.T_R = (config->t_r & 0x3FFu);
    timing1.f.T_F = (config->t_f & 0x1FFu);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timing1.w);

    // TIMING2: START condition timing
    i2c__TIMING2_t timing2 = {.w = 0};
    timing2.f.TSU_STA = (config->tsu_sta & 0x1FFFu);
    timing2.f.THD_STA = (config->thd_sta & 0x1FFFu);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timing2.w);

    // TIMING3: Data timing
    i2c__TIMING3_t timing3 = {.w = 0};
    timing3.f.TSU_DAT = (config->tsu_dat & 0x1FFu);
    timing3.f.THD_DAT = (config->thd_dat & 0x1FFFu);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timing3.w);

    // TIMING4: STOP and bus free timing
    i2c__TIMING4_t timing4 = {.w = 0};
    timing4.f.TSU_STO = (config->tsu_sto & 0x1FFFu);
    timing4.f.T_BUF = (config->t_buf & 0x1FFFu);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timing4.w);
}

/* Set when i2c_reset_fifos() had to drain the ACQ FIFO by hand because ACQRST
 * left entries behind. A test that wants to prove the hardware reset works reads
 * this instead of trusting the post-condition the helper itself produces.
 *
 * Cleared at the top of every i2c_reset_fifos() call, so it describes only the
 * most recent one -- which is what the header promises and what a test asserting
 * immediately after the call needs. */
/* Driver-internal scratch tracing, off by default.
 *
 * scratch[1] is the FW<->cocotb handshake channel that most testcases in this
 * suite poll, and scratch[0] is the pass/fail channel, so a driver write to
 * either while a handshake is pending overwrites the testcase's own marker or
 * verdict with a debug value, and the failure looks like the testcase hanging
 * or reporting the wrong state with nothing pointing at the driver.
 *
 * Nothing depends on these values -- all 42 are markers -- so they are
 * compiled out unless a debugger asks for them. Define I2C_DRIVER_SCRATCH_TRACE
 * to get them back, and only in a build whose testcase does not use the
 * scratch handshake. */
#ifdef I2C_DRIVER_SCRATCH_TRACE
#define i2c_trace_scratch(idx, val) write_scratch((idx), (val))
#else
#define i2c_trace_scratch(idx, val) ((void)(idx), (void)(val))
#endif

uint32_t g_i2c_acq_reset_needed_drain;
uint32_t g_i2c_acq_reset_residual; /* ACQLVL still left when the drain gave up */

/* How many entries the drain actually removed. This separates the two causes
 * that g_i2c_acq_reset_needed_drain alone cannot tell apart: a count near the
 * pre-reset level means ACQRST did nothing, while a small count means ACQRST
 * emptied the FIFO and an still-active controller refilled it before the level
 * was read back. The first is a hardware question and the second is a race in
 * the caller's check, so a test must not conclude either without this number. */
uint32_t g_i2c_acq_reset_drained;

/* Same idea for the controller-side FIFOs: RXRST needing a software drain, and
 * FMTRST needing a second attempt (with the level left behind after it). */
uint32_t g_i2c_rx_reset_needed_drain;
uint32_t g_i2c_rx_reset_residual; /* RXLVL still left when the drain gave up */
uint32_t g_i2c_fmt_reset_needed_retry;
uint32_t g_i2c_fmt_reset_residual;
uint32_t g_i2c_tx_reset_needed_retry; /* TXRST needed a second attempt */
uint32_t g_i2c_tx_reset_residual;     /* TXLVL after that second attempt */

/* Fail-closed by default. When a FIFO reset does not take, the code below
 * repairs the FIFO by hand, and the caller's "level is 0 after reset" check is
 * then satisfied by that repair rather than by the hardware. Every test calling
 * this helper on its setup path inherits the blind spot, and four independent
 * audits filed it, so the helper now terminates the test rather than hide it.
 *
 * Measured across 12 recent runs the repair path fires zero times, so failing
 * closed is not load-bearing in healthy operation. A test that deliberately
 * provokes a stuck FIFO sets this to 1 for the window in which it expects a
 * repair, which puts that expectation in the source instead of leaving it
 * silently global. */
uint32_t g_i2c_reset_repair_allowed;

/* Bound on the manual drain. The ACQ FIFO is 64 deep
 * (smc_config_pkg::I2C_TARGET_RX_FIFO_DEPTH), so anything beyond a small
 * multiple of that means the level is not falling. */
#define I2C_ACQ_DRAIN_BOUND 256u

void i2c_reset_fifos(uint32_t idx, bool reset_rx, bool reset_fmt, bool reset_tx, bool reset_acq) {
    uint32_t base = i2c_get_base(idx);

    /* Describe this call only -- see the declarations above. */
    g_i2c_acq_reset_needed_drain = 0;
    g_i2c_acq_reset_drained = 0;
    g_i2c_acq_reset_residual = 0;
    g_i2c_rx_reset_needed_drain = 0;
    g_i2c_rx_reset_residual = 0;
    g_i2c_fmt_reset_needed_retry = 0;
    g_i2c_fmt_reset_residual = 0;
    g_i2c_tx_reset_needed_retry = 0;
    g_i2c_tx_reset_residual = 0;

    // Step 1: Write FIFO reset bits
    // Reference: OpenTitan FIFO Guide Section 2.1 - FIFO Reset & Preparation
    i2c__FIFO_CTRL_t fifo_ctrl = {.w = 0};
    fifo_ctrl.f.RXRST = reset_rx ? 1 : 0;
    fifo_ctrl.f.FMTRST = reset_fmt ? 1 : 0;
    fifo_ctrl.f.TXRST = reset_tx ? 1 : 0;
    fifo_ctrl.f.ACQRST = reset_acq ? 1 : 0;

    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fifo_ctrl.w);

    // Step 2: Verify FIFO levels are 0 (Crucial Step per OpenTitan FIFO guide)
    // Reference: OpenTitan I2C FIFO documentation, Section 2.1
    // "Verify (Crucial Step): read HOST_FIFO_STATUS or TARGET_FIFO_STATUS.
    // Confirm RX/ACQ FIFO Level is 0. Confirm FMT/TX FIFO Level is 0 (and TX Empty)."

    // Small delay to allow FIFO reset to propagate through hardware
    for (volatile int i = 0; i < 100; i++)
        ;

    if (reset_rx || reset_fmt) {
        // Verify Controller (Host) FIFOs
        i2c__HOST_FIFO_STATUS_t host_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        /* RX: bounded drain, and the repair is recorded.
         *
         * Same defect the ACQ branch had -- an unbounded `while` that could only
         * end in a simulator timeout, and a post-condition (level 0) produced by
         * the helper rather than by RXRST, so a caller checking "empty after
         * reset" was checking this loop. */
        if (reset_rx && host_status.f.RXLVL != 0) {
            uint32_t drained = 0;
            g_i2c_rx_reset_needed_drain = 1;
            while (host_status.f.RXLVL > 0 && drained < I2C_ACQ_DRAIN_BOUND) {
                (void)i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR(0) -
                                           SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                host_status.w =
                    i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                drained++;
            }
            /* The last level actually read. Non-zero means the bound expired
             * with the FIFO still filling, which the gate below turns into a
             * failure that names the level instead of a silent spin. */
            g_i2c_rx_reset_residual = host_status.f.RXLVL;
        }

        /* FMT: re-apply the reset, then re-read the level, so a second failure
         * is reported to the caller rather than assumed away. */
        if (reset_fmt && host_status.f.FMTLVL != 0) {
            g_i2c_fmt_reset_needed_retry = 1;
            fifo_ctrl.w = 0;
            fifo_ctrl.f.FMTRST = 1;
            i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                          fifo_ctrl.w);
            for (volatile int i = 0; i < 100; i++)
                ;
            host_status.w =
                i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            g_i2c_fmt_reset_residual = host_status.f.FMTLVL;
        }
    }

    if (reset_tx || reset_acq) {
        // Verify Target FIFOs
        i2c__TARGET_FIFO_STATUS_t target_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        /* TX: re-apply the reset, then re-read the level. Callers assert
         * "TXLVL is 0 after reset" on their setup path, so that post-condition
         * has to be the hardware's, not a blind retry's. */
        if (reset_tx && target_status.f.TXLVL != 0) {
            g_i2c_tx_reset_needed_retry = 1;
            fifo_ctrl.w = 0;
            fifo_ctrl.f.TXRST = 1;
            i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                          fifo_ctrl.w);
            for (volatile int i = 0; i < 100; i++)
                ;
            target_status.w =
                i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                     SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            g_i2c_tx_reset_residual = target_status.f.TXLVL;
        }

        /* Verify ACQ FIFO Level = 0 -- and report, rather than repair.
         *
         * A drain by hand would make ACQLVL == 0 the helper's doing regardless
         * of whether the hardware reset worked, and any caller checking "the
         * FIFO is empty after a reset" would be checking this loop, not the DUT.
         *
         * The drain stays, because callers depend on the FIFO being empty when
         * this returns, but it is bounded and the fact that repair was needed is
         * recorded in g_i2c_acq_reset_needed_drain so a test can assert on it.
         */
        if (reset_acq && target_status.f.ACQLVL != 0) {
            uint32_t drained = 0;
            g_i2c_acq_reset_needed_drain = 1;
            while (target_status.f.ACQLVL > 0 && drained < I2C_ACQ_DRAIN_BOUND) {
                (void)i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                           SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                target_status.w =
                    i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                         SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                drained++;
            }
            /* See the RX branch: the last level actually read, so an expired
             * bound reports the level it gave up at. */
            g_i2c_acq_reset_residual = target_status.f.ACQLVL;
            g_i2c_acq_reset_drained = drained;
        }
    }

    /* Fail closed on any repair the caller did not ask for.
     *
     * Reaching here with a flag set means a FIFO reset did not take and the
     * post-condition every caller relies on was manufactured in software. That
     * is a real DUT observation, and continuing would launder it into a PASS. */
    if (!g_i2c_reset_repair_allowed &&
        (g_i2c_acq_reset_needed_drain || g_i2c_rx_reset_needed_drain ||
         g_i2c_fmt_reset_needed_retry || g_i2c_tx_reset_needed_retry)) {
        simputs("[I2C][reset_fifos] FIFO reset did not take; software repair was needed. idx=");
        simputshex32("", idx);
        simputs(" acq_drain=");
        simputshex32("", g_i2c_acq_reset_needed_drain);
        simputs(" rx_drain=");
        simputshex32("", g_i2c_rx_reset_needed_drain);
        simputs(" fmt_retry=");
        simputshex32("", g_i2c_fmt_reset_needed_retry);
        simputs(" tx_retry=");
        simputshex32("", g_i2c_tx_reset_needed_retry);
        simputs(" acq_residual=");
        simputshex32("", g_i2c_acq_reset_residual);
        simputs(" rx_residual=");
        simputshex32("", g_i2c_rx_reset_residual);
        simputs(" fmt_residual=");
        simputshex32("", g_i2c_fmt_reset_residual);
        simputs(" tx_residual=");
        simputshex32("", g_i2c_tx_reset_residual);
        simputs("\n");
        test_fail(0);
    }
}

// ============================================================================
// Controller Mode Functions Implementation
// ============================================================================

int i2c_controller_init(uint32_t idx, const i2c_controller_config_t *config) {
    uint32_t base = i2c_get_base(idx);

    // Disable controller first
    i2c__CTRL_t ctrl = {.w = 0};
    ctrl.f.ENABLEHOST = 0;
    ctrl.f.ENABLETARGET = 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    // Reset FIFOs
    i2c_reset_fifos(idx, true, true, false, false);

    // Configure timing
    if (config && config->timing.thigh > 0) {
        i2c_config_timing(idx, &config->timing);
    } else {
        i2c_timing_config_t default_timing;
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &default_timing);
        i2c_config_timing(idx, &default_timing);
    }

    // Configure FIFO thresholds
    i2c__HOST_FIFO_CONFIG_t fifo_cfg = {.w = 0};
    if (config) {
        fifo_cfg.f.RX_THRESH = config->fifo.rx_thresh;
        fifo_cfg.f.FMT_THRESH = config->fifo.fmt_thresh;
    } else {
        fifo_cfg.f.RX_THRESH = I2C_DEFAULT_RX_THRESH;
        fifo_cfg.f.FMT_THRESH = I2C_DEFAULT_FMT_THRESH;
    }
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fifo_cfg.w);

    // Clear all interrupts
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  0xFFFFFFFF);

    // Configure controller timeout (per i2c_controller_driver.c)
    uint32_t timeout_val = (config && config->timeout_cycles > 0)
                               ? config->timeout_cycles
                               : 0xFFFFFF; // Default large timeout
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_TIMEOUT_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timeout_val);

    i2c__TIMEOUT_CTRL_t timeout_ctrl = {.w = 0};
    timeout_ctrl.f.VAL = timeout_val;
    timeout_ctrl.f.MODE = 1; // Enable timeout in controller mode
    timeout_ctrl.f.EN = 1;   // Enable timeout
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timeout_ctrl.w);

    // Enable interrupts if requested
    if (config && config->enable_interrupts) {
        i2c__INTR_ENABLE_t intr_en = {.w = 0};
        intr_en.f.FMT_THRESHOLD = 1;
        intr_en.f.RX_THRESHOLD = 1;
        intr_en.f.CONTROLLER_HALT = 1;
        intr_en.f.CMD_COMPLETE = 1;
        intr_en.f.RX_OVERFLOW = 1;
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      intr_en.w);
    }

    // Enable Controller mode
    ctrl.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    ctrl.f.ENABLEHOST = 1;
    ctrl.f.ENABLETARGET = 0;
    ctrl.f.TX_STRETCH_CTRL_EN = 1; // CRITICAL: Enable TX clock stretching for VIP/slow slaves
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

void i2c_controller_disable(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ENABLEHOST = 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
}

void i2c_controller_enable(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ENABLEHOST = 1;
    ctrl.f.ENABLETARGET = 0;
    ctrl.f.TX_STRETCH_CTRL_EN = 1; // Enable TX clock stretching (important for VIP/slow slaves)
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
}

bool i2c_controller_is_idle(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return (status.f.HOSTIDLE != 0);
}

int i2c_controller_wait_idle(uint32_t idx, uint32_t timeout_cycles) {
    uint32_t base = i2c_get_base(idx);
    uint32_t count = 0;
    // Use the passed timeout_cycles parameter, with a minimum of 10 to prevent infinite loops
    uint32_t effective_timeout = (timeout_cycles > 0) ? timeout_cycles : 10;

    while (1) {
        i2c__STATUS_t status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (status.f.HOSTIDLE) {
            return I2C_OK;
        }

        count++;
        if (count >= effective_timeout) {
            return I2C_ERROR_TIMEOUT;
        }
    }
}

#define I2C_FMT_SPACE_BOUND 100000u

/* Push one FDATA entry, waiting for FMT space first.
 *
 * The RTL exposes STATUS.FMTFULL (= !fmt_fifo_wready, i2c_core.sv:258) and the
 * FDATA write is not gated on wready, so a push into a full FMT FIFO is simply
 * dropped: with CONTROLLER_TX_FIFO_DEPTH = 64 (smc_config_pkg.sv:23) an
 * unconditional 64-byte write is 65 entries and loses at least one.
 *
 * Returns I2C_ERROR_TIMEOUT if space never appears, so callers can tell a
 * dropped byte from a delivered one.
 */
static int fdata_push_wait_space(uint32_t base, uint32_t word, uint32_t bound) {
    uint32_t i;
    for (i = 0; i < bound; i++) {
        i2c__STATUS_t st = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (!st.f.FMTFULL) {
            i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                          word);
            return I2C_OK;
        }
    }
    return I2C_ERROR_TIMEOUT;
}

int i2c_controller_write(uint32_t idx, uint8_t target_addr, const uint8_t *data, uint32_t len,
                         bool send_stop) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);

    // Repeated START support: the controller stays busy between transactions of a repeated
    // START sequence, so wait for idle only when hostidle=1 (previous transaction sent STOP).
    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (status.f.HOSTIDLE) {
        // Controller was idle, wait for it to be ready
        int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) return ret;
    }

    // Send START + address (write bit = 0)
    // If controller was busy, this becomes a Repeated START automatically
    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = (target_addr << 1) | 0x0;
    fdata.f.START = 1;
    fdata.f.READB = 0;
    if (fdata_push_wait_space(base, fdata.w, I2C_FMT_SPACE_BOUND) != I2C_OK) {
        return I2C_ERROR_TIMEOUT;
    }

    // Send data bytes
    for (uint32_t i = 0; i < len; i++) {
        fdata.w = 0;
        fdata.f.FBYTE = data[i];
        fdata.f.STOP = (send_stop && (i == len - 1)) ? 1 : 0;
        fdata.f.READB = 0;
        if (fdata_push_wait_space(base, fdata.w, I2C_FMT_SPACE_BOUND) != I2C_OK) {
            return I2C_ERROR_TIMEOUT;
        }
    }

    // Wait for FMT FIFO to empty so the next START is not issued while
    // this transaction's entries are still being shifted out.
    if (!send_stop) {
        // Repeated START: FMT FIFO empty means START + address + data have gone.
        uint32_t wait_count = 0;
        const uint32_t MAX_WAIT = 10000;
        i2c__STATUS_t status;

        while (wait_count < MAX_WAIT) {
            status.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            if (status.f.FMTEMPTY) {
                // FMT FIFO is empty, all entries have been processed
                break;
            }
            wait_count++;
        }

        if (wait_count >= MAX_WAIT) {
            // Report the expiry: without it control falls through to the
            // `return I2C_OK` below and a caller cannot tell "every FMT entry
            // was transmitted" from "the FIFO never drained in 10000 polls",
            // which makes every caller's `if (ret != I2C_OK)` branch dead for
            // this failure mode.
            return I2C_ERROR_TIMEOUT;
        }
    } else {
        // For STOP transaction: Wait for controller to become idle
        // This ensures transaction is completely finished
        int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
        if (ret != I2C_OK) return ret;
    }

    return I2C_OK;
}

int i2c_controller_read(uint32_t idx, uint8_t target_addr, uint8_t *data, uint32_t len,
                        bool send_stop) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);
    // Target-side debug reads assume the internal pairing: I2C_1 controller, I2C_0 target.
    uint32_t target_idx_for_debug = (idx == 1) ? 0 : 0; // Default to 0 for I2C_0

    // Debug marker: Enter function
    i2c_trace_scratch(1, 0x00000090); // Enter i2c_controller_read

    // Repeated START: the controller stays busy between the transactions of a
    // repeated-START sequence, so wait for idle only when hostidle=1 (the
    // previous transaction sent STOP); hostidle=0 means continue directly.
    i2c_trace_scratch(1, 0x00000091); // Before idle check
    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (status.f.HOSTIDLE) {
        // Controller was idle, wait for it to be ready
        i2c_trace_scratch(1, 0x00000092); // hostidle=1, waiting
        int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
        i2c_trace_scratch(1, 0x00000093); // After wait_idle
        if (ret != I2C_OK) {
            i2c_trace_scratch(1, 0x00000094); // Error: wait_idle failed
            // Check for controller events on timeout
            uint32_t events = i2c_get_controller_events(idx);
            if (events != 0) {
                // Controller may be halted due to error
                return I2C_ERROR_BUSY;
            }
            return ret;
        }
    } else {
        // Controller is busy - this is a Repeated START, continue directly
        i2c_trace_scratch(1, 0x00000095); // hostidle=0, Repeated START
    }

    // =========================================================================
    // Controller FSM constraint (i2c_controller_fsm.sv): from POP_FMT_FIFO the FSM returns to
    // IDLE when fmt_fifo_depth_i == 1, so a READ command that is the last FMT entry never
    // executes and the read hangs. Keep the depth above 1 across the address/read-command
    // pair: wait for two free FMT slots, then write both entries back to back so the FSM sees
    // depth >= 2 when it pops the address entry.
    // =========================================================================

    const uint32_t FMT_FIFO_DEPTH = 64;
    const uint32_t MIN_REQUIRED_SLOTS = 2; // Need 2 slots for address + read command

    // Wait for FMT FIFO to have at least 2 free slots
    i2c_trace_scratch(1, 0x00000096); // Before waiting for FMT FIFO space
    uint32_t fifo_wait_count = 0;
    const uint32_t FIFO_WAIT_TIMEOUT = I2C_TIMEOUT_DEFAULT;

    while (fifo_wait_count < FIFO_WAIT_TIMEOUT) {
        i2c__HOST_FIFO_STATUS_t fifo_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        uint32_t available_slots = FMT_FIFO_DEPTH - fifo_status.f.FMTLVL;

        if (available_slots >= MIN_REQUIRED_SLOTS) {
            break; // FMT FIFO has enough space for both entries
        }

        fifo_wait_count++;
        if (fifo_wait_count % 1000 == 0) {
            // Periodic delay to avoid tight polling
            for (volatile int i = 0; i < 10; i++)
                ;
        }
    }

    if (fifo_wait_count >= FIFO_WAIT_TIMEOUT) {
        i2c_trace_scratch(1, 0x00000097); // Error: FMT FIFO timeout
        return I2C_ERROR_TIMEOUT;
    }
    i2c_trace_scratch(1, 0x00000098); // FMT FIFO ready (at least 2 slots available)

    // CRITICAL: Write both FMT entries consecutively with minimal delay
    // This ensures depth >= 2 when FSM starts processing
    i2c__FDATA_t fdata = {.w = 0};

    // Entry 1: Send START + address (read bit = 1)
    // If controller was busy, this becomes a Repeated START automatically
    i2c_trace_scratch(1, 0x00000099); // Before sending START+address
    fdata.f.FBYTE = (target_addr << 1) | 0x1;
    fdata.f.START = 1;
    fdata.f.READB = 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);

    // Entry 2: Send read command (write immediately after Entry 1)
    i2c_trace_scratch(1, 0x0000009A); // Before sending read command
    fdata.w = 0;
    fdata.f.FBYTE = (len & 0xFF); // Number of bytes to read (0 = 256)
    fdata.f.READB = 1;
    // RCONT bit: 0 = NACK last byte (Read Stop), 1 = ACK last byte (Read Continue)
    // For repeated START transactions (send_stop=false), rcont must be 1 to ACK the last byte
    // and allow the transaction to continue. For normal transactions (send_stop=true), rcont=0 to
    // NACK.
    fdata.f.RCONT =
        send_stop ? 0 : 1; // ACK last byte if continuing (repeated START), NACK if stopping
    fdata.f.STOP = send_stop ? 1 : 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);
    i2c_trace_scratch(1, 0x0000009B); // After sending both FMT entries

    // At this point, FMT FIFO contains 2 entries:
    //   - Entry 1: START + ADDR + R (depth changes 0->1 or N->N+1)
    //   - Entry 2: READ command      (depth changes 1->2 or N+1->N+2)
    // When FSM processes Entry 1, depth will be >= 1 (Entry 2 still in FIFO)
    // This avoids the fmt_fifo_depth_i == 1 condition triggering prematurely

    // Read data from RX FIFO
    i2c_trace_scratch(1, 0x0000009C); // Before reading RX FIFO loop
    uint32_t timeout = I2C_TIMEOUT_DEFAULT;
    for (uint32_t i = 0; i < len; i++) {
        // Wait for data in RX FIFO
        i2c_trace_scratch(1, 0x0000009D); // Before waiting for RX data (iteration i)
        uint32_t count = 0;
        uint32_t last_events_check = 0;
        while (1) {
            i2c__STATUS_t status = {
                .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            if (!status.f.RXEMPTY) break;

            // Check for controller errors while waiting (every 1000 cycles to avoid too many
            // scratch writes)
            if ((count % 1000) == 0) {
                uint32_t events = i2c_get_controller_events(idx);
                if (events != last_events_check) {
                    // Events changed - record to scratchpad
                    if (events & 0x1) {
                        i2c_trace_scratch(1, 0x0000009E); // Error: NACK detected
                        // Debug: Log Target status when NACK occurs (only if idx=1, meaning I2C_1
                        // Controller)
                        if (idx == 1) {
                            uint32_t tgt_tx_level, tgt_acq_level;
                            i2c_target_get_fifo_status(target_idx_for_debug, &tgt_tx_level,
                                                       &tgt_acq_level);
                            // Encode debug info: 0x9A000000 | (tgt_tx_level & 0xFF) << 8 |
                            // (tgt_acq_level & 0xFF)
                            uint32_t debug_info =
                                0x9A000000 | ((tgt_tx_level & 0xFF) << 8) | (tgt_acq_level & 0xFF);
                            i2c_trace_scratch(0, debug_info);
                        }
                        return I2C_ERROR_NACK;
                    }
                    if (events & 0x8) {
                        i2c_trace_scratch(1, 0x0000009F); // Error: Arbitration lost
                        return I2C_ERROR;
                    }
                    if (events & 0x4) {
                        i2c_trace_scratch(1, 0x000000A0); // Error: Bus timeout
                        return I2C_ERROR_TIMEOUT;
                    }
                    last_events_check = events;
                }

                // Periodic debug: Check Target status every 10000 cycles (only if idx=1, meaning
                // I2C_1 Controller)
                if ((count % 10000) == 0 && count > 0 && idx == 1) {
                    uint32_t tgt_tx_level, tgt_acq_level;
                    i2c_target_get_fifo_status(target_idx_for_debug, &tgt_tx_level, &tgt_acq_level);
                    // Encode debug info: 0xA5000000 | (events & 0xFF) << 16 | (tgt_tx_level & 0xFF)
                    // << 8 | (tgt_acq_level & 0xFF)
                    uint32_t debug_info = 0xA5000000 | ((events & 0xFF) << 16) |
                                          ((tgt_tx_level & 0xFF) << 8) | (tgt_acq_level & 0xFF);
                    i2c_trace_scratch(0, debug_info);
                    i2c_trace_scratch(1, 0x000000A1); // Debug: Periodic status check

                    // The target FSM sets TX_PENDING as soon as the read command arrives; while
                    // it is set, unhandled_tx_stretch_event_i holds the clock stretch and the
                    // target cannot send. Clearing TARGET_EVENTS during the wait releases it.
                    uint32_t target_events = i2c_get_target_events(target_idx_for_debug);
                    if (target_events != 0) {
                        // Clear TARGET_EVENTS to release clock stretch
                        i2c_clear_target_events(target_idx_for_debug, 0xFFFFFFFF);
                        // Small delay to allow hardware to update
                        for (volatile uint32_t j = 0; j < 10; j++) {
                            __asm__("nop");
                        }
                    }
                }
            }

            count++;
            if (count >= timeout) {
                i2c_trace_scratch(1, 0x000000A2); // Error: Timeout waiting for RX data
                // Check events one more time before returning timeout
                uint32_t events = i2c_get_controller_events(idx);
                // Debug: Log final status when timeout occurs (only if idx=1, meaning I2C_1
                // Controller)
                if (idx == 1) {
                    uint32_t tgt_tx_level, tgt_acq_level;
                    i2c_target_get_fifo_status(target_idx_for_debug, &tgt_tx_level, &tgt_acq_level);
                    // Encode debug info: 0x9F000000 | (events & 0xFF) << 16 | (tgt_tx_level & 0xFF)
                    // << 8 | (tgt_acq_level & 0xFF)
                    uint32_t debug_info = 0x9F000000 | ((events & 0xFF) << 16) |
                                          ((tgt_tx_level & 0xFF) << 8) | (tgt_acq_level & 0xFF);
                    i2c_trace_scratch(0, debug_info);
                }
                if (events != 0) {
                    // Return specific error based on events
                    if (events & 0x1) return I2C_ERROR_NACK;
                    if (events & 0x4) return I2C_ERROR_TIMEOUT;
                    return I2C_ERROR;
                }
                return I2C_ERROR_TIMEOUT;
            }
        }

        // Read data byte
        i2c_trace_scratch(1, 0x000000A3); // Before reading data byte
        i2c__RDATA_t rdata = {.w =
                                  i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR(0) -
                                                       SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        data[i] = (uint8_t)rdata.f.DATA;
        i2c_trace_scratch(1, 0x000000A4); // After reading data byte
    }

    // =========================================================================
    // Internal I2C (I2C_1 controller <-> I2C_0 target): a pure read leaves START + ADDRESS +
    // READ_BIT entries in the target ACQ FIFO, and an ACQ depth > 1 triggers stretch_tx and
    // hangs the bus, so the target ACQ FIFO is drained after every successful read.
    // =========================================================================
    i2c_trace_scratch(1, 0x000000A5); // Debug: Before draining ACQ FIFO

    // Only drain if this is I2C_1 Controller reading from I2C_0 Target
    if (idx == 1) {
        uint32_t target_base = i2c_get_base(target_idx_for_debug);
        uint32_t drain_timeout = 1000;
        uint32_t drained_count = 0;

        // Drain all entries from Target ACQ FIFO
        while (drain_timeout > 0) {
            i2c__STATUS_t tgt_status = {
                .w = i2c_read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                 SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

            if (tgt_status.f.ACQEMPTY) {
                // ACQ FIFO is empty, done
                break;
            }

            // Read and discard ACQ FIFO entry
            (void)i2c_read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            drained_count++;
            drain_timeout--;

            // Avoid infinite loop
            if (drained_count > 64) {
                // ACQ FIFO depth is 64, should never drain more
                i2c_trace_scratch(1, 0x000000A6); // Warning: Drained too many entries
                break;
            }
        }

        if (drained_count > 0) {
            i2c_trace_scratch(1, 0x000000A4); // Debug: ACQ FIFO drained successfully
            // Optionally log drained count to scratch[0] for debugging
        }

        // TX_PENDING is sticky and re-arms while event_read_cmd_received is high; while it is
        // set, unhandled_tx_stretch_event_i blocks clock-stretch release, so TARGET_EVENTS is
        // cleared until it reads back 0.
        uint32_t clear_attempts = 0;
        const uint32_t MAX_CLEAR_ATTEMPTS = 10;

        while (clear_attempts < MAX_CLEAR_ATTEMPTS) {
            uint32_t target_events = i2c_get_target_events(target_idx_for_debug);
            if (target_events == 0) {
                // TARGET_EVENTS is cleared, done
                break;
            }

            // Clear TARGET_EVENTS (write 1 to clear sticky bits)
            i2c_clear_target_events(target_idx_for_debug, 0xFFFFFFFF);
            clear_attempts++;

            // Small delay to allow hardware to update
            for (volatile uint32_t i = 0; i < 10; i++) {
                __asm__("nop");
            }
        }
    }

    i2c_trace_scratch(1, 0x000000A2); // Before return (success)
    return I2C_OK;
}

int i2c_controller_write_read(uint32_t idx, uint8_t target_addr, const uint8_t *write_data,
                              uint32_t write_len, uint8_t *read_data, uint32_t read_len) {
    int ret;

    // Write phase (no STOP)
    ret = i2c_controller_write(idx, target_addr, write_data, write_len, false);
    if (ret != I2C_OK) return ret;

    // Read phase (with STOP)
    ret = i2c_controller_read(idx, target_addr, read_data, read_len, true);
    return ret;
}

/**
 * @brief Clear Target ACQ FIFO and TARGET_EVENTS
 *
 * Helper function to clean up Target ACQ FIFO and events.
 *
 * @param target_idx Target I2C instance index
 */
static void i2c_target_clear_acq_fifo(uint32_t target_idx) {
    // Reset the ACQ FIFO (ACQRST) before each transaction to prevent stretch_tx.
    i2c_reset_fifos(target_idx, false, false, false, true);

    // Clear any unhandled TARGET_EVENTS that might cause stretch_tx
    uint32_t target_events = i2c_get_target_events(target_idx);
    if (target_events != 0) {
        i2c_clear_target_events(target_idx, 0xFFFFFFFF); // Clear all events
    }

    // Verify ACQ FIFO is empty after reset
    if (!i2c_target_acq_fifo_empty(target_idx)) {
        uint32_t drain_base = i2c_get_base(target_idx);
        while (!i2c_target_acq_fifo_empty(target_idx)) {
            (void)i2c_read_reg(drain_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                             SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
        }
    }
}

int i2c_write_with_clear(uint32_t controller_idx, uint32_t target_idx, uint8_t target_addr,
                         const uint8_t *data, uint32_t len, bool send_stop) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    // Perform controller write operation
    int ret = i2c_controller_write(controller_idx, target_addr, data, len, send_stop);
    if (ret != I2C_OK) return ret;

    // Clear Target ACQ FIFO and TARGET_EVENTS after write
    // According to OpenTitan standard, ACQ FIFO must be empty before next transaction
    // If ACQ FIFO depth > 1 when next transaction arrives, stretch_tx will be triggered
    i2c_target_clear_acq_fifo(target_idx);

    return I2C_OK;
}

int i2c_read_with_clear(uint32_t controller_idx, uint32_t target_idx, uint8_t target_addr,
                        uint8_t *data, uint32_t len, bool send_stop) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    // Perform controller read operation
    int ret = i2c_controller_read(controller_idx, target_addr, data, len, send_stop);
    if (ret != I2C_OK) return ret;

    // CRITICAL: Drain Target ACQ FIFO after read operation
    // Pure read operations leave ACQ FIFO entries (START + ADDRESS + READ_BIT)
    // These must be drained to prevent stretch_tx in next transaction
    uint32_t target_base = i2c_get_base(target_idx);
    uint32_t drain_count = 0;
    uint32_t drain_timeout = 1000;

    while (drain_timeout > 0 && !i2c_target_acq_fifo_empty(target_idx)) {
        // Read and discard ACQ FIFO entry
        (void)i2c_read_reg(target_base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));

        drain_count++;
        drain_timeout--;

        // Safety check: ACQ FIFO depth is 64
        if (drain_count > 64) {
            break;
        }
    }

    return I2C_OK;
}

int i2c_controller_write_with_header(uint32_t idx, uint8_t target_addr, const uint8_t *data,
                                     uint32_t len) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);

    // Wait for controller idle
    int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) return ret;

// =========================================================================
// FMT FIFO write handshake
// =========================================================================
// The RTL assumes (i2c_fifos.sv):
//
// `ASSUME(FmtWriteStableBeforeHandshake_A,
//         fmt_fifo_wvalid_i && !fmt_fifo_wready_o
//         |=> $stable(fmt_fifo_wvalid_i) && $stable(fmt_fifo_wdata_i))
//
// Translation: If FIFO write request (wvalid=1) is not immediately accepted
// (wready=0), then wvalid and wdata MUST remain stable in the next cycle.
//
// Critical Understanding:
// - "FIFO has space" (fmtlvl check) ≠ "FIFO ready for next write" (wready)
// - Each write needs individual handshake completion
// - STATUS.FMTFULL directly reflects wready state
//
// Solution: Check STATUS.FMTFULL before EACH FDATA write
// - FMTFULL=0 means wready=1, safe to write
// - This ensures proper handshake timing for every transaction
// =========================================================================

// Helper macro: Wait for FIFO to be NOT FULL before writing
// FMTFULL is the inverse of fmt_fifo_wready, so FMTFULL=0 means ready
#define WAIT_FIFO_NOT_FULL() \
    do { \
        uint32_t timeout = 5000; \
        i2c__STATUS_t status; \
        while (timeout > 0) { \
            status.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - \
                                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0))); \
            if (status.f.FMTFULL == 0) break; \
            timeout--; \
        } \
        if (timeout == 0) return I2C_ERROR_TIMEOUT; \
    } while (0)

    i2c__FDATA_t fdata = {.w = 0};

    // Send START + address (write)
    WAIT_FIFO_NOT_FULL(); // Ensure FIFO ready before write
    fdata.f.FBYTE = (target_addr << 1) | 0x0;
    fdata.f.START = 1;
    fdata.f.READB = 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);

    // Send length header
    WAIT_FIFO_NOT_FULL(); // Ensure FIFO ready before write
    fdata.w = 0;
    fdata.f.FBYTE = (len & 0xFF);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);

    // Send data bytes with STOP on last
    for (uint32_t i = 0; i < len; i++) {
        WAIT_FIFO_NOT_FULL(); // CRITICAL: Check before EACH write!
        fdata.w = 0;
        fdata.f.FBYTE = data[i];
        if (i == len - 1) {
            fdata.f.STOP = 1;
        }
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      fdata.w);
    }

#undef WAIT_FIFO_NOT_FULL
    return I2C_OK;
}

int i2c_controller_write_with_header_nonblock(uint32_t idx, uint8_t target_addr,
                                              const uint8_t *data, uint32_t len) {
    if (!data || len == 0) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);

// Does not wait for the controller to go idle: the caller runs this alongside
// target-side reads, and blocking here deadlocks once the controller FSM is
// busy while the target ACQ FIFO is full.

// Helper macro: Wait for FIFO to be NOT FULL before writing (assertion compliant)
// FMTFULL is the inverse of fmt_fifo_wready, so FMTFULL=0 means ready
#define WAIT_FIFO_NOT_FULL() \
    do { \
        uint32_t timeout = 5000; \
        i2c__STATUS_t status; \
        while (timeout > 0) { \
            status.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) - \
                                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0))); \
            if (status.f.FMTFULL == 0) break; \
            timeout--; \
        } \
        if (timeout == 0) return I2C_ERROR_TIMEOUT; \
    } while (0)

    // Send START + address (write)
    WAIT_FIFO_NOT_FULL(); // Ensure FIFO ready before write
    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = (target_addr << 1) | 0x0;
    fdata.f.START = 1;
    fdata.f.READB = 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);

    // Send length header
    WAIT_FIFO_NOT_FULL(); // Ensure FIFO ready before write
    fdata.w = 0;
    fdata.f.FBYTE = (len & 0xFF);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);

    // Send data bytes with STOP on last
    for (uint32_t i = 0; i < len; i++) {
        WAIT_FIFO_NOT_FULL(); // CRITICAL: Check before EACH write!
        fdata.w = 0;
        fdata.f.FBYTE = data[i];
        if (i == len - 1) {
            fdata.f.STOP = 1;
        }
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      fdata.w);
    }

#undef WAIT_FIFO_NOT_FULL
    // Return immediately without waiting for transaction to complete
    // Hardware FSM will execute the I2C transaction in the background
    return I2C_OK;
}

void i2c_controller_get_fifo_status(uint32_t idx, uint32_t *fmt_level, uint32_t *rx_level) {
    uint32_t base = i2c_get_base(idx);

    i2c__HOST_FIFO_STATUS_t status = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (fmt_level) *fmt_level = status.f.FMTLVL;
    if (rx_level) *rx_level = status.f.RXLVL;
}

/**
 * @brief Wait for FMT FIFO to have available space
 *
 * This function helps prevent FIFO overflow by waiting for space to become
 * available before writing to the FMT FIFO.
 *
 * @param idx I2C instance index
 * @param required_space Number of entries needed in FIFO
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if space available, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_controller_wait_fmt_fifo_space(uint32_t idx, uint32_t required_space,
                                       uint32_t timeout_cycles) {
    uint32_t base = i2c_get_base(idx);
    uint32_t count = 0;

    // FMT FIFO depth is 64 entries
    const uint32_t FMT_FIFO_DEPTH = 64;

    while (1) {
        i2c__HOST_FIFO_STATUS_t status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        uint32_t available_space = FMT_FIFO_DEPTH - status.f.FMTLVL;
        if (available_space >= required_space) {
            return I2C_OK;
        }

        if (timeout_cycles > 0) {
            count++;
            if (count >= timeout_cycles) {
                return I2C_ERROR_TIMEOUT;
            }
        }
    }
}

/**
 * @brief Wait for RX FIFO to have data available
 *
 * @param idx I2C instance index
 * @param required_entries Number of entries needed in FIFO
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if data available, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_controller_wait_rx_fifo_data(uint32_t idx, uint32_t required_entries,
                                     uint32_t timeout_cycles) {
    uint32_t base = i2c_get_base(idx);
    uint32_t count = 0;

    while (1) {
        i2c__HOST_FIFO_STATUS_t status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (status.f.RXLVL >= required_entries) {
            return I2C_OK;
        }

        if (timeout_cycles > 0) {
            count++;
            if (count >= timeout_cycles) {
                return I2C_ERROR_TIMEOUT;
            }
        }
    }
}

/**
 * @brief Wait for ACQ FIFO to have data available (Target mode)
 *
 * @param idx I2C instance index
 * @param required_entries Number of entries needed in FIFO
 * @param timeout_cycles Maximum cycles to wait (0 = infinite)
 * @return I2C_OK if data available, I2C_ERROR_TIMEOUT if timeout
 */
int i2c_target_wait_acq_fifo_data(uint32_t idx, uint32_t required_entries,
                                  uint32_t timeout_cycles) {
    uint32_t base = i2c_get_base(idx);
    uint32_t count = 0;

    while (1) {
        i2c__TARGET_FIFO_STATUS_t status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (status.f.ACQLVL >= required_entries) {
            return I2C_OK;
        }

        if (timeout_cycles > 0) {
            count++;
            if (count >= timeout_cycles) {
                return I2C_ERROR_TIMEOUT;
            }
        }
    }
}

// ============================================================================
// Target Mode Functions Implementation
// ============================================================================

int i2c_target_init(uint32_t idx, const i2c_target_config_t *config) {
    uint32_t base = i2c_get_base(idx);

    // Disable target first
    i2c__CTRL_t ctrl = {.w = 0};
    ctrl.f.ENABLEHOST = 0;
    ctrl.f.ENABLETARGET = 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    // Reset FIFOs
    i2c_reset_fifos(idx, false, false, true, true);

    // Configure timing
    if (config && config->timing.thigh > 0) {
        i2c_config_timing(idx, &config->timing);
    } else {
        i2c_timing_config_t default_timing;
        i2c_get_default_timing(I2C_SPEED_STANDARD, 100, &default_timing);
        i2c_config_timing(idx, &default_timing);
    }

    // Set target address
    i2c__TARGET_ID_t target_id = {.w = 0};
    if (config) {
        target_id.f.ADDRESS0 = config->address0 & 0x7F;
        target_id.f.MASK0 = config->mask0 & 0x7F;
        target_id.f.ADDRESS1 = config->address1 & 0x7F;
        target_id.f.MASK1 = config->mask1 & 0x7F;
    } else {
        target_id.f.ADDRESS0 = 0x10; // Default address
        target_id.f.MASK0 = 0x7F;    // Exact match
    }
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  target_id.w);

    // Configure FIFO thresholds
    i2c__TARGET_FIFO_CONFIG_t fifo_cfg = {.w = 0};
    if (config) {
        fifo_cfg.f.TX_THRESH = config->fifo.tx_thresh;
        fifo_cfg.f.ACQ_THRESH = config->fifo.acq_thresh;
    } else {
        fifo_cfg.f.TX_THRESH = I2C_DEFAULT_TX_THRESH;
        fifo_cfg.f.ACQ_THRESH = I2C_DEFAULT_ACQ_THRESH;
    }
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_CONFIG_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fifo_cfg.w);

    // Clear all interrupts
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  0xFFFFFFFF);

    // Configure control options
    ctrl.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    if (config) {
        ctrl.f.ACK_CTRL_EN = config->ack_ctrl_mode ? 1 : 0;
        ctrl.f.TX_STRETCH_CTRL_EN = config->tx_stretch_ctrl ? 1 : 0;
    }

    // Enable interrupts if requested
    if (config && config->enable_interrupts) {
        i2c__INTR_ENABLE_t intr_en = {.w = 0};
        intr_en.f.ACQ_THRESHOLD = 1;
        intr_en.f.TX_THRESHOLD = 1;
        intr_en.f.TX_STRETCH = 1;
        intr_en.f.ACQ_STRETCH = 1;
        intr_en.f.UNEXP_STOP = 1;
        intr_en.f.CMD_COMPLETE = 1;
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      intr_en.w);
    }

    // Enable Target mode
    ctrl.f.ENABLEHOST = 0;
    ctrl.f.ENABLETARGET = 1;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

void i2c_target_disable(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ENABLETARGET = 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
}

bool i2c_target_is_idle(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return (status.f.TARGETIDLE != 0);
}

void i2c_target_set_address(uint32_t idx, uint8_t address0, uint8_t mask0) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ID_t target_id = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    target_id.f.ADDRESS0 = address0 & 0x7F;
    target_id.f.MASK0 = mask0 & 0x7F;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  target_id.w);
}

void i2c_target_set_address_secondary(uint32_t idx, uint8_t address1, uint8_t mask1) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ID_t target_id = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    target_id.f.ADDRESS1 = address1 & 0x7F;
    target_id.f.MASK1 = mask1 & 0x7F;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  target_id.w);
}

uint32_t i2c_target_transmit(uint32_t idx, const uint8_t *data, uint32_t len) {
    if (!data || len == 0) return 0;

    uint32_t base = i2c_get_base(idx);
    uint32_t written = 0;

    // Debug marker: Enter function
    // Use scratch[1] = 0x00000080 to indicate function entry
    // Note: This is a common function, so we use a high marker value to avoid conflicts
    i2c_trace_scratch(1, 0x00000080); // Enter i2c_target_transmit

    for (uint32_t i = 0; i < len; i++) {
        // Debug marker: Before checking TX FIFO status
        // Use scratch[1] = 0x00000081 + i to track loop iterations
        if (i == 0) {
            i2c_trace_scratch(1, 0x00000081); // Before first iteration
        }

        // TX FIFO space is judged from the TXLVL level, not the txfull flag (OpenTitan FIFO
        // flow guide).
        i2c__TARGET_FIFO_STATUS_t fifo_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        // Debug marker: After reading FIFO STATUS register
        if (i == 0) {
            i2c_trace_scratch(1, 0x00000082); // After reading FIFO STATUS
        }

        // TXLVL below the FIFO depth means space is available.
        uint32_t tx_level = fifo_status.f.TXLVL;
        /* The target TX FIFO is 64 deep (smc_config_pkg::I2C_TARGET_TX_FIFO_DEPTH).
         * A TXDATA write into a full FIFO is silently dropped, so stop here and
         * let the caller's "did every byte get pushed?" guard fire. */
        if (tx_level >= I2C_TARGET_TX_FIFO_DEPTH) break;

        // Debug marker: Before writing TXDATA
        if (i == 0) {
            i2c_trace_scratch(1, 0x00000083); // Before writing TXDATA
        }

        // Write data byte
        i2c__TXDATA_t txdata = {.w = 0};
        txdata.f.DATA = data[i];
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      txdata.w);

        // Debug marker: After writing TXDATA
        if (i == 0) {
            i2c_trace_scratch(1, 0x00000084); // After writing TXDATA
        }

        written++;
    }

    // Debug marker: Before return
    if (written > 0) {
        i2c_trace_scratch(1, 0x00000085); // Before return (success)
    }

    return written;
}

int i2c_target_receive_entry(uint32_t idx, i2c_acq_entry_t *entry) {
    if (!entry) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);

    // Check if ACQ FIFO has data
    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    if (status.f.ACQEMPTY) {
        return I2C_ERROR;
    }

    // Read ACQ data
    i2c__ACQDATA_t acqdata = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    entry->signal = (uint8_t)acqdata.f.SIGNAL;
    entry->data = (uint8_t)acqdata.f.ABYTE;

    // Decode signal type
    /* Set before the switch so every leg, including default, is covered. */
    entry->is_nack = (entry->signal == I2C_ACQ_SIGNAL_NACK) ||
                     (entry->signal == I2C_ACQ_SIGNAL_NACK_START) ||
                     (entry->signal == I2C_ACQ_SIGNAL_NACK_STOP);

    switch (entry->signal) {
    case I2C_ACQ_SIGNAL_START:
    case I2C_ACQ_SIGNAL_RESTART:
        entry->is_start = true;
        entry->is_stop = false;
        entry->is_write = (entry->data & 0x01) == 0;
        break;

    case I2C_ACQ_SIGNAL_STOP:
    case I2C_ACQ_SIGNAL_NACK_STOP:
        entry->is_start = false;
        entry->is_stop = true;
        entry->is_write = false;
        break;

    default:
        entry->is_start = false;
        entry->is_stop = false;
        entry->is_write = true; // Assume write for data bytes
        break;
    }

    return I2C_OK;
}

/* Framing is now explicit.
 *
 * This helper unconditionally treated the first ACQ data byte as a length
 * header, which is right for the callers that send one and silently wrong for
 * the callers that do not. i2c_p1_dma sends the standard no-header format, so
 * its first payload byte (0x00) became length_header = 0; the next byte then
 * satisfied `len >= length_header` and the function returned I2C_OK with
 * received_len = 1 after a 64-byte write -- structurally incapable of reporting
 * more than one byte no matter what the RTL did. The kept log recorded exactly
 * that: "Received 0x00000001".
 *
 * i2c_target_receive_transaction keeps its old name, signature and
 * header-framing behaviour so its 27 other call sites are unaffected; callers
 * that send raw bytes now have a variant that says so.
 */
int i2c_target_receive_transaction_framed(uint32_t idx, uint8_t *buffer, uint32_t buffer_size,
                                          uint32_t *received_len, uint32_t timeout_cycles,
                                          bool expect_length_header) {
    if (!buffer || !received_len || buffer_size == 0) return I2C_ERROR_INVALID;

    uint32_t base = i2c_get_base(idx);
    uint32_t count = 0;
    uint32_t len = 0;
    uint32_t length_header = 0xFFFFFFFF;
    int in_txn = 0;
    int saw_stop = 0; /* the only clean way out of the drain loop */

    // Two-stage receive: first a short non-blocking check so data the
    // controller has already pushed is drained before the ACQ FIFO overflows,
    // then the standard OpenTitan blocking wait if the FIFO is still empty.

    // Step 1: Quick check if FIFO already has data (non-blocking, short wait)
    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (status.f.ACQEMPTY) {
        // FIFO is empty, do a short non-blocking wait first
        // This handles the case where Controller just finished sending
        // and data is still being written to ACQ FIFO
        uint32_t short_wait_count = 0;
        const uint32_t SHORT_WAIT_CYCLES = 1000;

        while (short_wait_count < SHORT_WAIT_CYCLES) {
            status.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
            if (!status.f.ACQEMPTY) break; // Data arrived, proceed to read
            short_wait_count++;
        }

        // Step 2: still empty, blocking wait
        if (status.f.ACQEMPTY) {
            int ret = i2c_target_wait_acq_fifo_data(idx, 1, timeout_cycles);
            if (ret != I2C_OK) {
                return ret; // Timeout or error
            }
        }
    }

    // Step 3: Process ACQ FIFO entries (OpenTitan standard pattern)
    // Add timeout protection to prevent infinite hang
    uint32_t loop_timeout = timeout_cycles > 0 ? timeout_cycles : (I2C_TIMEOUT_DEFAULT * 10);
    uint32_t loop_count = 0;

    while (1) {
        status.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                        SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));

        // Timeout protection: prevent infinite loop
        if (timeout_cycles > 0) {
            loop_count++;
            if (loop_count >= loop_timeout) {
                *received_len = len;
                return I2C_ERROR_TIMEOUT;
            }
        }

        // If FIFO is empty and not in transaction, we're done
        if (status.f.ACQEMPTY && in_txn == 0) {
            break; // Transaction complete
        }

        // If FIFO is empty but in transaction, wait for more data
        if (status.f.ACQEMPTY && in_txn != 0) {
            // Brief wait for next FIFO entry
            count = 0;
            /* Bounded by the caller's timeout_cycles so a stall on this path
             * cannot outlive the budget the caller sized against its harness;
             * 10000 stays the ceiling when the caller passes none. */
            uint32_t inter_byte_timeout =
                (timeout_cycles > 0u && timeout_cycles < 10000u) ? timeout_cycles : 10000u;
            while (count < inter_byte_timeout) {
                status.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
                if (!status.f.ACQEMPTY) break;
                count++;
            }

            /* Inter-byte expiry is a timeout, not a completion: a truncated or
             * stalled transfer must reach the caller as an error, or every
             * caller's `if (ret != I2C_OK)` is a dead branch for it. */
            if (status.f.ACQEMPTY) {
                *received_len = len;
                return I2C_ERROR_TIMEOUT;
            }
        }

        if (!status.f.ACQEMPTY) {
            i2c__ACQDATA_t acq = {
                .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            uint32_t signal = acq.f.SIGNAL;
            uint8_t abyte = (uint8_t)acq.f.ABYTE;

            // START or Repeated START
            if (signal == I2C_ACQ_SIGNAL_START || signal == I2C_ACQ_SIGNAL_RESTART) {
                in_txn = 1;
                length_header = 0xFFFFFFFF;
                len = 0;
                continue;
            }

            // STOP or NACK_STOP
            if (signal == I2C_ACQ_SIGNAL_STOP || signal == I2C_ACQ_SIGNAL_NACK_STOP) {
                in_txn = 0;
                saw_stop = 1;
                break;
            }

            // Data byte (ACKed)
            if (signal == I2C_ACQ_SIGNAL_DATA) {
                if (expect_length_header && length_header == 0xFFFFFFFF) {
                    // First byte is length header
                    length_header = abyte;
                } else {
                    // Subsequent bytes are data
                    if (len < buffer_size) {
                        buffer[len++] = abyte;
                    } else {
                        // Buffer overflow - abort
                        *received_len = len;
                        return I2C_ERROR_OVERFLOW;
                    }

                    // Repeated START (no STOP): once every data byte named by the
                    // length header has arrived, return without waiting for STOP so
                    // i2c_target_receive_transaction() works inside a repeated-START
                    // sequence.
                    if (expect_length_header && length_header != 0xFFFFFFFF &&
                        len >= length_header) {
                        // All data bytes received according to length header
                        // Return immediately (no need to wait for STOP in repeated START scenario)
                        *received_len = len;
                        return I2C_OK;
                    }
                }
            }
        }
    }

    *received_len = len;
    /* Reached here without a STOP means the loop left via the
     * "FIFO empty and never in a transaction" exit at the top -- nothing ever
     * arrived. Reporting that as success is what let a caller print a pass line
     * over an empty buffer. A framed read that ended on its length header is
     * not affected: it returns I2C_OK explicitly from inside the loop. */
    if (!saw_stop) {
        return I2C_ERROR_TIMEOUT;
    }
    return I2C_OK;
}

int i2c_target_receive_transaction(uint32_t idx, uint8_t *buffer, uint32_t buffer_size,
                                   uint32_t *received_len, uint32_t timeout_cycles) {
    /* Unchanged behaviour for existing callers: first data byte is a length
     * header. New callers that send raw bytes should call
     * i2c_target_receive_transaction_framed(..., false) instead. */
    return i2c_target_receive_transaction_framed(idx, buffer, buffer_size, received_len,
                                                 timeout_cycles, true);
}

void i2c_target_get_fifo_status(uint32_t idx, uint32_t *tx_level, uint32_t *acq_level) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_FIFO_STATUS_t status = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (tx_level) *tx_level = status.f.TXLVL;
    if (acq_level) *acq_level = status.f.ACQLVL;
}

bool i2c_target_acq_fifo_empty(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return (status.f.ACQEMPTY != 0);
}

bool i2c_target_tx_fifo_full(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__STATUS_t status = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    return (status.f.TXFULL != 0);
}

// ============================================================================
// Status and Interrupt Functions Implementation
// ============================================================================

uint32_t i2c_get_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    return i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
}

uint32_t i2c_get_interrupt_state(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    return i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
}

void i2c_clear_interrupts(uint32_t idx, uint32_t intr_mask) {
    uint32_t base = i2c_get_base(idx);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  intr_mask);
}

void i2c_enable_interrupts(uint32_t idx, uint32_t intr_mask) {
    uint32_t base = i2c_get_base(idx);

    uint32_t current = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  current | intr_mask);
}

void i2c_disable_interrupts(uint32_t idx, uint32_t intr_mask) {
    uint32_t base = i2c_get_base(idx);

    uint32_t current = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                                            SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  current & ~intr_mask);
}

uint32_t i2c_get_controller_events(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    return i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0) -
                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
}

void i2c_clear_controller_events(uint32_t idx, uint32_t event_mask) {
    uint32_t base = i2c_get_base(idx);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CONTROLLER_EVENTS_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  event_mask);
}

uint32_t i2c_get_target_events(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    return i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR(0) -
                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
}

void i2c_clear_target_events(uint32_t idx, uint32_t event_mask) {
    uint32_t base = i2c_get_base(idx);
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  event_mask);
}

// ============================================================================
// Advanced Configuration Functions Implementation
// ============================================================================

void i2c_config_timeout(uint32_t idx, uint32_t timeout_val, bool stretch_mode, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__TIMEOUT_CTRL_t timeout_ctrl = {.w = 0};
    timeout_ctrl.f.VAL = timeout_val & 0x3FFFFFFF;
    timeout_ctrl.f.MODE = stretch_mode ? 0 : 1;
    timeout_ctrl.f.EN = enable ? 1 : 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timeout_ctrl.w);
}

void i2c_config_nack_timeout(uint32_t idx, uint32_t timeout_val, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__HOST_NACK_HANDLER_TIMEOUT_t nack_timeout = {.w = 0};
    nack_timeout.f.VAL = timeout_val & 0x7FFFFFFF;
    nack_timeout.f.EN = enable ? 1 : 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_NACK_HANDLER_TIMEOUT_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  nack_timeout.w);
}

void i2c_set_loopback(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.LLPBK = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);
}

void i2c_target_config_ack_ctrl(uint32_t idx, bool enable, uint16_t nbytes) {
    uint32_t base = i2c_get_base(idx);

    // Configure ACK control mode in CTRL register
    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ctrl.f.ACK_CTRL_EN = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    // Set number of bytes to ACK
    if (enable) {
        i2c__TARGET_ACK_CTRL_t ack_ctrl = {.w = 0};
        ack_ctrl.f.NBYTES = nbytes & 0x1FF;
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      ack_ctrl.w);
    }
}

void i2c_target_send_nack(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ACK_CTRL_t ack_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    ack_ctrl.f.NACK = 1;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  ack_ctrl.w);
}

// ============================================================================
// SMBus Functions Implementation
// ============================================================================

void i2c_smbus_suspend(uint32_t idx, bool assert) {
    uint32_t base = i2c_get_base(idx);

    i2c__SMBUS_CTRL_t smbus_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    smbus_ctrl.f.SMBSUS = assert ? 1 : 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  smbus_ctrl.w);
}

void i2c_smbus_alert(uint32_t idx, bool assert) {
    uint32_t base = i2c_get_base(idx);

    i2c__SMBUS_CTRL_t smbus_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
    smbus_ctrl.f.SMBALERT = assert ? 1 : 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  smbus_ctrl.w);
}

uint32_t i2c_get_smbus_status(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);
    return i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_STATUS_BASE_ADDR(0) -
                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)));
}

uint8_t smbus_calculate_pec(const uint8_t *data, uint16_t len, uint8_t init_crc) {
    uint8_t crc = init_crc;

    for (uint16_t i = 0; i < len; i++) {
        crc ^= data[i];

        for (uint8_t bit = 0; bit < 8; bit++) {
            if (crc & 0x80) {
                crc = (crc << 1) ^ SMBUS_PEC_POLYNOMIAL;
            } else {
                crc = crc << 1;
            }
        }
    }

    return crc;
}

int smbus_quick_command(uint32_t idx, uint8_t device_addr, bool write_bit) {
    uint32_t base = i2c_get_base(idx);

    // Wait for controller idle
    int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) return ret;

    // Send START + address with R/W bit + STOP
    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = (device_addr << 1) | (write_bit ? 0 : 1);
    fdata.f.START = 1;
    fdata.f.STOP = 1; // Quick command has no data, just address
    fdata.f.READB = 0;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);

    return I2C_OK;
}

int smbus_send_byte(uint32_t idx, uint8_t device_addr, uint8_t data, bool use_pec) {
    uint8_t pec = 0;

    if (use_pec) {
        uint8_t pec_data[2];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        pec_data[1] = data;
        pec = smbus_calculate_pec(pec_data, 2, 0);
    }

    uint8_t tx_data[2];
    tx_data[0] = data;
    uint8_t len = 1;

    if (use_pec) {
        tx_data[1] = pec;
        len = 2;
    }

    return i2c_controller_write(idx, device_addr, tx_data, len, true);
}

int smbus_receive_byte(uint32_t idx, uint8_t device_addr, uint8_t *data, bool use_pec) {
    if (!data) return I2C_ERROR_INVALID;

    uint8_t len = use_pec ? 2 : 1;
    uint8_t buffer[2];

    int ret = i2c_controller_read(idx, device_addr, buffer, len, true);
    if (ret != I2C_OK) return ret;

    if (use_pec) {
        // Verify PEC
        uint8_t pec_data[2];
        pec_data[0] = (device_addr << 1) | 0x1; // Address + read
        pec_data[1] = buffer[0];
        uint8_t calc_pec = smbus_calculate_pec(pec_data, 2, 0);

        if (calc_pec != buffer[1]) {
            return I2C_ERROR; // PEC mismatch
        }
    }

    *data = buffer[0];
    return I2C_OK;
}

int smbus_write_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t data,
                     bool use_pec) {
    uint8_t pec = 0;

    if (use_pec) {
        uint8_t pec_data[3];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        pec_data[1] = command;
        pec_data[2] = data;
        pec = smbus_calculate_pec(pec_data, 3, 0);
    }

    uint8_t tx_data[3];
    tx_data[0] = command;
    tx_data[1] = data;
    uint8_t len = 2;

    if (use_pec) {
        tx_data[2] = pec;
        len = 3;
    }

    return i2c_controller_write(idx, device_addr, tx_data, len, true);
}

int smbus_read_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data,
                    bool use_pec) {
    if (!data) return I2C_ERROR_INVALID;

    // Write command code
    int ret = i2c_controller_write(idx, device_addr, &command, 1, false);
    if (ret != I2C_OK) return ret;

    // Read data byte (+ PEC if enabled)
    uint8_t len = use_pec ? 2 : 1;
    uint8_t buffer[2];

    ret = i2c_controller_read(idx, device_addr, buffer, len, true);
    if (ret != I2C_OK) return ret;

    if (use_pec) {
        // Verify PEC
        uint8_t pec_data[4];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        pec_data[1] = command;
        pec_data[2] = (device_addr << 1) | 0x1; // Address + read
        pec_data[3] = buffer[0];
        uint8_t calc_pec = smbus_calculate_pec(pec_data, 4, 0);

        if (calc_pec != buffer[1]) {
            return I2C_ERROR; // PEC mismatch
        }
    }

    *data = buffer[0];
    return I2C_OK;
}

int smbus_write_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t data,
                     bool use_pec) {
    uint8_t pec = 0;

    if (use_pec) {
        uint8_t pec_data[4];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        pec_data[1] = command;
        pec_data[2] = (uint8_t)(data & 0xFF);        // LSB
        pec_data[3] = (uint8_t)((data >> 8) & 0xFF); // MSB
        pec = smbus_calculate_pec(pec_data, 4, 0);
    }

    uint8_t tx_data[4];
    tx_data[0] = command;
    tx_data[1] = (uint8_t)(data & 0xFF);        // LSB first
    tx_data[2] = (uint8_t)((data >> 8) & 0xFF); // MSB
    uint8_t len = 3;

    if (use_pec) {
        tx_data[3] = pec;
        len = 4;
    }

    return i2c_controller_write(idx, device_addr, tx_data, len, true);
}

int smbus_read_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t *data,
                    bool use_pec) {
    if (!data) return I2C_ERROR_INVALID;

    // Write command code
    int ret = i2c_controller_write(idx, device_addr, &command, 1, false);
    if (ret != I2C_OK) return ret;

    // Read 2 data bytes (+ PEC if enabled)
    uint8_t len = use_pec ? 3 : 2;
    uint8_t buffer[3];

    ret = i2c_controller_read(idx, device_addr, buffer, len, true);
    if (ret != I2C_OK) return ret;

    if (use_pec) {
        // Verify PEC
        uint8_t pec_data[5];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        pec_data[1] = command;
        pec_data[2] = (device_addr << 1) | 0x1; // Address + read
        pec_data[3] = buffer[0];                // LSB
        pec_data[4] = buffer[1];                // MSB
        uint8_t calc_pec = smbus_calculate_pec(pec_data, 5, 0);

        if (calc_pec != buffer[2]) {
            return I2C_ERROR; // PEC mismatch
        }
    }

    *data = ((uint16_t)buffer[1] << 8) | buffer[0]; // MSB, LSB
    return I2C_OK;
}

int smbus_block_write(uint32_t idx, uint8_t device_addr, uint8_t command, const uint8_t *data,
                      uint8_t len, bool use_pec) {
    if (!data || len == 0 || len > 255) return I2C_ERROR_INVALID;

    uint8_t tx_buffer[258]; // command + count + data + PEC
    uint8_t tx_len = 0;

    tx_buffer[tx_len++] = command;
    tx_buffer[tx_len++] = len; // Byte count
    memcpy(&tx_buffer[tx_len], data, len);
    tx_len += len;

    if (use_pec) {
        // Calculate PEC over address + command + count + data
        uint8_t pec_data[259];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        memcpy(&pec_data[1], tx_buffer, tx_len);
        uint8_t pec = smbus_calculate_pec(pec_data, tx_len + 1, 0);
        tx_buffer[tx_len++] = pec;
    }

    return i2c_controller_write(idx, device_addr, tx_buffer, tx_len, true);
}

int smbus_block_read(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data,
                     uint8_t *len, uint8_t max_len, bool use_pec) {
    if (!data || !len || max_len == 0) return I2C_ERROR_INVALID;

    // Write command code
    int ret = i2c_controller_write(idx, device_addr, &command, 1, false);
    if (ret != I2C_OK) return ret;

    // Read byte count first
    uint8_t count;
    ret = i2c_controller_read(idx, device_addr, &count, 1, false);
    if (ret != I2C_OK) return ret;

    if (count > max_len) return I2C_ERROR_OVERFLOW;

    // Read data bytes (+ PEC if enabled)
    uint8_t read_len = count + (use_pec ? 1 : 0);
    uint8_t buffer[256];

    ret = i2c_controller_read(idx, device_addr, buffer, read_len, true);
    if (ret != I2C_OK) return ret;

    if (use_pec) {
        // Verify PEC
        uint8_t pec_data[259];
        uint16_t pec_len = 0;
        pec_data[pec_len++] = (device_addr << 1) | 0x0; // Address + write
        pec_data[pec_len++] = command;
        pec_data[pec_len++] = (device_addr << 1) | 0x1; // Address + read
        pec_data[pec_len++] = count;
        memcpy(&pec_data[pec_len], buffer, count);
        pec_len += count;

        uint8_t calc_pec = smbus_calculate_pec(pec_data, pec_len, 0);
        if (calc_pec != buffer[count]) {
            return I2C_ERROR; // PEC mismatch
        }
    }

    memcpy(data, buffer, count);
    *len = count;
    return I2C_OK;
}

int smbus_process_call(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t write_data,
                       uint16_t *read_data, bool use_pec) {
    if (!read_data) return I2C_ERROR_INVALID;

    uint8_t write_buffer[4]; // command + 2 bytes write data + PEC
    uint8_t write_len = 0;

    write_buffer[write_len++] = command;
    write_buffer[write_len++] = (uint8_t)(write_data & 0xFF);        // LSB
    write_buffer[write_len++] = (uint8_t)((write_data >> 8) & 0xFF); // MSB

    if (use_pec) {
        uint8_t pec_data[4];
        pec_data[0] = (device_addr << 1) | 0x0; // Address + write
        memcpy(&pec_data[1], write_buffer, 3);
        uint8_t pec = smbus_calculate_pec(pec_data, 4, 0);
        write_buffer[write_len++] = pec;
    }

    // Write phase (no STOP)
    int ret = i2c_controller_write(idx, device_addr, write_buffer, write_len, false);
    if (ret != I2C_OK) return ret;

    // Read phase (2 bytes + PEC if enabled)
    uint8_t read_len = use_pec ? 3 : 2;
    uint8_t read_buffer[3];

    ret = i2c_controller_read(idx, device_addr, read_buffer, read_len, true);
    if (ret != I2C_OK) return ret;

    if (use_pec) {
        // Verify PEC
        uint8_t pec_data[8];
        uint8_t pec_len = 0;
        pec_data[pec_len++] = (device_addr << 1) | 0x0; // Address + write
        memcpy(&pec_data[pec_len], write_buffer, write_len - (use_pec ? 1 : 0));
        pec_len += write_len - (use_pec ? 1 : 0);
        pec_data[pec_len++] = (device_addr << 1) | 0x1; // Address + read
        pec_data[pec_len++] = read_buffer[0];
        pec_data[pec_len++] = read_buffer[1];

        uint8_t calc_pec = smbus_calculate_pec(pec_data, pec_len, 0);
        if (calc_pec != read_buffer[2]) {
            return I2C_ERROR; // PEC mismatch
        }
    }

    *read_data = ((uint16_t)read_buffer[1] << 8) | read_buffer[0];
    return I2C_OK;
}

int smbus_block_process_call(uint32_t idx, uint8_t device_addr, uint8_t command,
                             const uint8_t *write_data, uint8_t write_len, uint8_t *read_data,
                             uint8_t *read_len, uint8_t max_read_len, bool use_pec) {
    if (!write_data || !read_data || !read_len || write_len == 0) return I2C_ERROR_INVALID;

    uint8_t write_buffer[258]; // command + count + data + PEC
    uint8_t total_write_len = 0;

    write_buffer[total_write_len++] = command;
    write_buffer[total_write_len++] = write_len;
    memcpy(&write_buffer[total_write_len], write_data, write_len);
    total_write_len += write_len;

    if (use_pec) {
        uint8_t pec_data[259];
        pec_data[0] = (device_addr << 1) | 0x0;
        memcpy(&pec_data[1], write_buffer, total_write_len);
        uint8_t pec = smbus_calculate_pec(pec_data, total_write_len + 1, 0);
        write_buffer[total_write_len++] = pec;
    }

    // Write phase (no STOP)
    int ret = i2c_controller_write(idx, device_addr, write_buffer, total_write_len, false);
    if (ret != I2C_OK) return ret;

    // Read count byte
    uint8_t count;
    ret = i2c_controller_read(idx, device_addr, &count, 1, false);
    if (ret != I2C_OK) return ret;

    if (count > max_read_len) return I2C_ERROR_OVERFLOW;

    // Read data bytes (+ PEC if enabled)
    uint8_t total_read_len = count + (use_pec ? 1 : 0);
    uint8_t read_buffer[256];

    ret = i2c_controller_read(idx, device_addr, read_buffer, total_read_len, true);
    if (ret != I2C_OK) return ret;

    if (use_pec) {
        // PEC verification is not implemented for block process call; a PEC request fails.
        return I2C_ERROR;
    }

    memcpy(read_data, read_buffer, count);
    *read_len = count;
    return I2C_OK;
}

int smbus_alert_response(uint32_t idx, uint8_t *alert_addr) {
    if (!alert_addr) return I2C_ERROR_INVALID;

    // Debug marker: Enter function
    i2c_trace_scratch(1, 0x00000086); // Enter smbus_alert_response

    // Read from Alert Response Address (0x0C)
    i2c_trace_scratch(1, 0x00000087); // Before calling i2c_controller_read
    uint8_t addr_byte = 0;
    int ret = i2c_controller_read(idx, SMBUS_ADDR_ARA, &addr_byte, 1, true);
    i2c_trace_scratch(1, 0x00000088); // After i2c_controller_read returned

    if (ret == I2C_OK) {
        i2c_trace_scratch(1, 0x00000089); // Before extracting address
        *alert_addr = (addr_byte >> 1);   // Extract 7-bit address
        i2c_trace_scratch(1, 0x0000008A); // After extracting address
    } else {
        i2c_trace_scratch(1, 0x0000008B); // Error path
        // On error, set alert_addr to 0xFF to indicate failure
        *alert_addr = 0xFF;
    }

    i2c_trace_scratch(1, 0x0000008C); // Before return
    return ret;
}

// ============================================================================
// PMBus Functions Implementation
// ============================================================================

int pmbus_send_byte(uint32_t idx, uint8_t device_addr, uint8_t command) {
    return i2c_controller_write(idx, device_addr, &command, 1, true);
}

int pmbus_write_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t data) {
    uint8_t tx_data[2];
    tx_data[0] = command;
    tx_data[1] = data;

    return i2c_controller_write(idx, device_addr, tx_data, 2, true);
}

int pmbus_write_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t data) {
    uint8_t tx_data[3];
    tx_data[0] = command;
    tx_data[1] = (uint8_t)(data & 0xFF);        // LSB first
    tx_data[2] = (uint8_t)((data >> 8) & 0xFF); // MSB

    return i2c_controller_write(idx, device_addr, tx_data, 3, true);
}

int pmbus_read_byte(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data) {
    if (!data) return I2C_ERROR_INVALID;

    // Write command code
    int ret = i2c_controller_write(idx, device_addr, &command, 1, false);
    if (ret != I2C_OK) return ret;

    // Read data byte
    return i2c_controller_read(idx, device_addr, data, 1, true);
}

int pmbus_read_word(uint32_t idx, uint8_t device_addr, uint8_t command, uint16_t *data) {
    if (!data) return I2C_ERROR_INVALID;

    // Write command code
    int ret = i2c_controller_write(idx, device_addr, &command, 1, false);
    if (ret != I2C_OK) return ret;

    // Read 2 bytes (LSB first)
    uint8_t buffer[2];
    ret = i2c_controller_read(idx, device_addr, buffer, 2, true);
    if (ret != I2C_OK) return ret;

    *data = ((uint16_t)buffer[1] << 8) | buffer[0];
    return I2C_OK;
}

int pmbus_block_write(uint32_t idx, uint8_t device_addr, uint8_t command, const uint8_t *data,
                      uint8_t len) {
    if (!data || len == 0 || len > 255) return I2C_ERROR_INVALID;

    uint8_t tx_buffer[257]; // command + count + data
    tx_buffer[0] = command;
    tx_buffer[1] = len; // Byte count
    memcpy(&tx_buffer[2], data, len);

    return i2c_controller_write(idx, device_addr, tx_buffer, len + 2, true);
}

int pmbus_block_read(uint32_t idx, uint8_t device_addr, uint8_t command, uint8_t *data,
                     uint8_t *len, uint8_t max_len) {
    if (!data || !len || max_len == 0) return I2C_ERROR_INVALID;

    // Write command code
    int ret = i2c_controller_write(idx, device_addr, &command, 1, false);
    if (ret != I2C_OK) return ret;

    // Read byte count first
    uint8_t count;
    ret = i2c_controller_read(idx, device_addr, &count, 1, false);
    if (ret != I2C_OK) return ret;

    if (count > max_len) return I2C_ERROR_OVERFLOW;

    // Read data bytes
    ret = i2c_controller_read(idx, device_addr, data, count, true);
    if (ret != I2C_OK) return ret;

    *len = count;
    return I2C_OK;
}

int pmbus_block_write_read(uint32_t idx, uint8_t device_addr, uint8_t command,
                           const uint8_t *write_data, uint8_t write_len, uint8_t *read_data,
                           uint8_t *read_len, uint8_t max_read_len) {
    if (!write_data || !read_data || !read_len || write_len == 0) return I2C_ERROR_INVALID;

    uint8_t write_buffer[257]; // command + count + data
    write_buffer[0] = command;
    write_buffer[1] = write_len;
    memcpy(&write_buffer[2], write_data, write_len);

    // Write phase (no STOP)
    int ret = i2c_controller_write(idx, device_addr, write_buffer, write_len + 2, false);
    if (ret != I2C_OK) return ret;

    // Read count byte
    uint8_t count;
    ret = i2c_controller_read(idx, device_addr, &count, 1, false);
    if (ret != I2C_OK) return ret;

    if (count > max_read_len) return I2C_ERROR_OVERFLOW;

    // Read data bytes
    ret = i2c_controller_read(idx, device_addr, read_data, count, true);
    if (ret != I2C_OK) return ret;

    *read_len = count;
    return I2C_OK;
}

int pmbus_group_command(uint32_t idx, const uint8_t *device_addrs, const uint8_t *commands,
                        const uint8_t **data_arrays, const uint8_t *data_lens,
                        uint8_t num_devices) {
    if (!device_addrs || !commands || !data_arrays || !data_lens || num_devices == 0) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);

    // Wait for controller idle
    int ret = i2c_controller_wait_idle(idx, I2C_TIMEOUT_DEFAULT);
    if (ret != I2C_OK) return ret;

    // Group command uses repeated STARTs for each device
    for (uint8_t i = 0; i < num_devices; i++) {
        // Send START + address + write
        i2c__FDATA_t fdata = {.w = 0};
        fdata.f.FBYTE = (device_addrs[i] << 1) | 0x0;
        fdata.f.START = 1;
        fdata.f.READB = 0;
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      fdata.w);

        // Send command code
        fdata.w = 0;
        fdata.f.FBYTE = commands[i];
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      fdata.w);

        // Send data bytes
        for (uint8_t j = 0; j < data_lens[i]; j++) {
            fdata.w = 0;
            fdata.f.FBYTE = data_arrays[i][j];

            // STOP only on last byte of last device
            if (i == num_devices - 1 && j == data_lens[i] - 1) {
                fdata.f.STOP = 1;
            }

            i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                          fdata.w);
        }
    }

    return I2C_OK;
}

// ============================================================================
// PMBus Data Format Conversion Functions Implementation
// ============================================================================

#include <math.h>

pmbus_linear11_t pmbus_float_to_linear11(float value) {
    pmbus_linear11_t result;

    // Handle special cases
    if (value == 0.0f) {
        result.mantissa = 0;
        result.exponent = 0;
        return result;
    }

    // Find optimal exponent
    int exp = 0;
    float abs_val = (value < 0) ? -value : value;

    // Scale to mantissa range [-1024, 1023]
    while (abs_val >= 1024.0f && exp < 15) {
        abs_val /= 2.0f;
        exp++;
    }

    while (abs_val < 512.0f && exp > -16) {
        abs_val *= 2.0f;
        exp--;
    }

    // Round mantissa
    int16_t mantissa = (int16_t)(value * powf(2.0f, -exp));

    // Clamp mantissa to 11-bit signed range
    if (mantissa > 1023) mantissa = 1023;
    if (mantissa < -1024) mantissa = -1024;

    // Clamp exponent to 5-bit signed range
    if (exp > 15) exp = 15;
    if (exp < -16) exp = -16;

    result.mantissa = mantissa;
    result.exponent = (int8_t)exp;

    return result;
}

float pmbus_linear11_to_float(pmbus_linear11_t linear11) {
    return (float)linear11.mantissa * powf(2.0f, (float)linear11.exponent);
}

pmbus_linear16_t pmbus_float_to_linear16(float value, int8_t exponent) {
    pmbus_linear16_t result;

    result.exponent = exponent;

    // Calculate mantissa
    float scaled = value * powf(2.0f, -(float)exponent);

    // Round and clamp to 16-bit unsigned range
    uint32_t mantissa = (uint32_t)(scaled + 0.5f);
    if (mantissa > 65535) mantissa = 65535;

    result.mantissa = (uint16_t)mantissa;

    return result;
}

float pmbus_linear16_to_float(pmbus_linear16_t linear16) {
    return (float)linear16.mantissa * powf(2.0f, (float)linear16.exponent);
}

uint16_t pmbus_pack_linear11(pmbus_linear11_t linear11) {
    // Pack: [15:11] = exponent (5-bit signed), [10:0] = mantissa (11-bit signed)
    uint16_t packed = 0;

    // Pack exponent (5-bit signed, sign-extended)
    uint16_t exp = (uint16_t)(linear11.exponent & 0x1F) << 11;

    // Pack mantissa (11-bit signed)
    uint16_t man = (uint16_t)(linear11.mantissa & 0x7FF);

    packed = exp | man;

    return packed;
}

pmbus_linear11_t pmbus_unpack_linear11(uint16_t packed) {
    pmbus_linear11_t result;

    // Extract exponent (5-bit signed)
    int8_t exp = (int8_t)((packed >> 11) & 0x1F);

    // Sign-extend exponent from 5-bit to 8-bit
    if (exp & 0x10) {
        exp |= 0xE0; // Sign extend
    }

    // Extract mantissa (11-bit signed)
    int16_t man = (int16_t)(packed & 0x7FF);

    // Sign-extend mantissa from 11-bit to 16-bit
    if (man & 0x400) {
        man |= 0xF800; // Sign extend
    }

    result.exponent = exp;
    result.mantissa = man;

    return result;
}

// ============================================================================
// Debug and Test Functions Implementation
// ============================================================================

void i2c_override_signals(uint32_t idx, bool enable, bool scl_val, bool sda_val) {
    uint32_t base = i2c_get_base(idx);

    i2c__OVRD_t ovrd = {.w = 0};
    ovrd.f.TXOVRDEN = enable ? 1 : 0;
    ovrd.f.SCLVAL = scl_val ? 1 : 0;
    ovrd.f.SDAVAL = sda_val ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ovrd.w);
}

void i2c_get_signal_samples(uint32_t idx, uint16_t *scl_samples, uint16_t *sda_samples) {
    uint32_t base = i2c_get_base(idx);

    i2c__VAL_t val = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_VAL_BASE_ADDR(0) -
                                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (scl_samples) *scl_samples = (uint16_t)val.f.SCL_RX;
    if (sda_samples) *sda_samples = (uint16_t)val.f.SDA_RX;
}

int i2c_reg_verify_write(uint32_t base, uint32_t offset, uint32_t value) {
    i2c_write_reg(base + offset, value);

    uint32_t read_value = i2c_read_reg(base + offset);

    if (read_value != value) {
        return I2C_ERROR;
    }

    return I2C_OK;
}

// ============================================================================
// Utility Functions Implementation
// ============================================================================

const char *i2c_error_to_string(int error) {
    switch (error) {
    case I2C_OK:
        return "Success";
    case I2C_ERROR:
        return "General error";
    case I2C_ERROR_TIMEOUT:
        return "Timeout";
    case I2C_ERROR_NACK:
        return "NACK received";
    case I2C_ERROR_OVERFLOW:
        return "FIFO overflow";
    case I2C_ERROR_BUSY:
        return "Device busy";
    case I2C_ERROR_INVALID:
        return "Invalid parameter";
    default:
        return "Unknown error";
    }
}

void i2c_dump_registers(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    // No register-dump sink exists in this library; the function is a no-op.

    (void)base;
}

// ============================================================================
// Easy FIFO Management Functions (from i2c_controller_driver.c)
// ============================================================================
// These functions provide simpler, more conservative FIFO management
// with built-in debug output, similar to i2c_controller_driver.c

#define I2C_PARAM_FIFO_DEPTH 64u
#define I2C_DEFAULT_TIMEOUT_EASY 10000u

/**
 * @brief Reset Controller FIFOs (Easy version)
 *
 * Simple FIFO reset that resets all FIFOs at once.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 */
void i2c_reset_fifos_easy(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__FIFO_CTRL_t fifo_ctrl = {.w = 0};
    fifo_ctrl.f.RXRST = 1;
    fifo_ctrl.f.FMTRST = 1;
    fifo_ctrl.f.TXRST = 1;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fifo_ctrl.w);
}

/**
 * @brief Configure FIFO thresholds (Easy version)
 *
 * Simple threshold configuration for FMT and RX FIFOs.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param fmt_thresh FMT FIFO threshold
 * @param rx_thresh RX FIFO threshold
 */
void i2c_configure_threshold_easy(uint32_t idx, uint16_t fmt_thresh, uint16_t rx_thresh) {
    uint32_t base = i2c_get_base(idx);

    i2c__HOST_FIFO_CONFIG_t host_cfg = {.w = 0};
    host_cfg.f.FMT_THRESH = fmt_thresh;
    host_cfg.f.RX_THRESH = rx_thresh;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_CONFIG_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  host_cfg.w);
}

/**
 * @brief Wait for controller to become idle (Easy version)
 *
 * Simple polling loop waiting for hostidle status.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param timeout Timeout value (0 = use default)
 * @return I2C_OK on success, I2C_ERROR_TIMEOUT on timeout
 */
int i2c_controller_wait_idle_easy(uint32_t idx, uint32_t timeout) {
    uint32_t base = i2c_get_base(idx);
    uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT_EASY;

    while (remaining--) {
        i2c__STATUS_t status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
        if (status.f.HOSTIDLE) {
            return I2C_OK;
        }
    }

    simputs("[I2C_EASY][wait_idle] TIMEOUT\n");
    return I2C_ERROR_TIMEOUT;
}

/**
 * @brief Wait for FMT FIFO space (Easy version)
 *
 * Conservative FIFO space checking with dual verification:
 * 1. Check STATUS.fmtfull flag
 * 2. Verify fmtlvl < FIFO_DEPTH
 *
 * Includes periodic debug output every 4096 iterations.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param timeout Timeout value (0 = use default)
 * @return I2C_OK on success, I2C_ERROR_TIMEOUT on timeout
 */
int i2c_controller_wait_fmt_fifo_space_easy(uint32_t idx, uint32_t timeout) {
    uint32_t base = i2c_get_base(idx);
    uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT_EASY;
    uint32_t initial = remaining;

    while (remaining--) {
        i2c__STATUS_t status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        // Dual check: STATUS.fmtfull + FIFO level
        if (!status.f.FMTFULL) {
            i2c__HOST_FIFO_STATUS_t fifo = {
                .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            if (fifo.f.FMTLVL < I2C_PARAM_FIFO_DEPTH) {
                return I2C_OK;
            }
        }

        // Debug output every 4096 iterations (0xFFF mask)
        uint32_t elapsed = initial - remaining;
        if ((elapsed & 0xFFFu) == 0u) {
            simputs("[I2C_EASY][wait_fmt_space] polling...\n");
            simputs("  STATUS.fmtfull=");
            simputshex32("", status.f.FMTFULL);
            i2c__HOST_FIFO_STATUS_t fifo_dbg = {
                .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};
            simputs("  HOST_FIFO.fmtlvl=");
            simputshex32("", fifo_dbg.f.FMTLVL);
            simputs("  HOST_FIFO.rxlvl=");
            simputshex32("", fifo_dbg.f.RXLVL);
        }
    }

    simputs("[I2C_EASY][wait_fmt_space] TIMEOUT\n");
    return I2C_ERROR_TIMEOUT;
}

/**
 * @brief Wait for RX FIFO data (Easy version)
 *
 * Simple polling loop waiting for RX FIFO to reach desired level.
 * Includes periodic debug output every 4096 iterations.
 * Based on i2c_controller_driver.c implementation.
 *
 * @param idx I2C instance index
 * @param level Required RX FIFO level
 * @param timeout Timeout value (0 = use default)
 * @return I2C_OK on success, I2C_ERROR_TIMEOUT on timeout
 */
int i2c_controller_wait_rx_fifo_data_easy(uint32_t idx, uint32_t level, uint32_t timeout) {
    uint32_t base = i2c_get_base(idx);
    uint32_t remaining = timeout ? timeout : I2C_DEFAULT_TIMEOUT_EASY;
    uint32_t initial = remaining;

    while (remaining--) {
        i2c__HOST_FIFO_STATUS_t fifo = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (fifo.f.RXLVL >= level) {
            return I2C_OK;
        }

        // Debug output every 4096 iterations (0xFFF mask)
        uint32_t elapsed = initial - remaining;
        if ((elapsed & 0xFFFu) == 0u) {
            simputs("[I2C_EASY][wait_rx_level] polling...\n");
            simputs("  HOST_FIFO.rxlvl=");
            simputshex32("", fifo.f.RXLVL);
        }
    }

    simputs("[I2C_EASY][wait_rx_level] TIMEOUT\n");
    return I2C_ERROR_TIMEOUT;
}

// ============================================================================
// OpenTitan I2C DIF API equivalents
// ============================================================================

/**
 * @brief Enable clock timeout for controller or target mode
 *
 * Based on OpenTitan dif_i2c_enable_clock_timeout().
 * Supports two timeout modes:
 * - Stretch timeout: Maximum time target can stretch clock
 * - Bus timeout: Maximum time SCL can remain low (SMBus compatible)
 *
 * @param idx I2C instance index
 * @param timeout_type 0=disabled, 1=stretch timeout, 2=bus timeout
 * @param cycles Timeout duration in clock cycles
 * @return I2C_OK on success, I2C_ERROR_INVALID on invalid parameters
 */
int i2c_enable_clock_timeout(uint32_t idx, uint8_t timeout_type, uint32_t cycles) {
    if (timeout_type > 2) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);

    // Read TIMEOUT_CTRL register
    i2c__TIMEOUT_CTRL_t timeout_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    switch (timeout_type) {
    case 0: // Disabled
        timeout_ctrl.f.EN = 0;
        break;

    case 1: // Stretch timeout
        timeout_ctrl.f.EN = 1;
        timeout_ctrl.f.MODE = 0;                // Stretch timeout mode
        timeout_ctrl.f.VAL = cycles & 0xFFFFFF; // 24-bit timeout value
        break;

    case 2: // Bus timeout (SMBus compatible)
        timeout_ctrl.f.EN = 1;
        timeout_ctrl.f.MODE = 1;                // Bus timeout mode
        timeout_ctrl.f.VAL = cycles & 0xFFFFFF; // 24-bit timeout value
        break;
    }

    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  timeout_ctrl.w);
    return I2C_OK;
}

/**
 * @brief Set host timeout for target mode
 *
 * When operating as target, sets the duration after which to trigger
 * a host timeout interrupt if the controller stops clocking.
 *
 * @param idx I2C instance index
 * @param duration Timeout duration in clock cycles
 * @return I2C_OK on success
 */
int i2c_set_host_timeout(uint32_t idx, uint32_t duration) {
    uint32_t base = i2c_get_base(idx);

    i2c__HOST_TIMEOUT_CTRL_t host_timeout = {.w = 0};
    host_timeout.f.VAL = duration & 0xFFFFFF; // 24-bit timeout value
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_TIMEOUT_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  host_timeout.w);

    return I2C_OK;
}

/**
 * @brief Enable or disable ACK Control Mode
 *
 * When enabled, target uses Auto ACK Counter to control ACK/NACK responses.
 * This provides fine-grained control over when to accept or reject data.
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_ack_ctrl_set_enabled(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ctrl.f.ACK_CTRL_EN = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

/**
 * @brief Enable or disable target TX stretch control
 *
 * When enabled, target will stretch clock at the start of read transactions
 * until software provides data to TX FIFO.
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_target_tx_stretch_ctrl_set_enabled(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ctrl.f.TX_STRETCH_CTRL_EN = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

/**
 * @brief Enable or disable line loopback mode
 *
 * In loopback mode, the I2C block internally connects TX to RX for testing.
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_line_loopback_set_enabled(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ctrl.f.LLPBK = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

/**
 * @brief Enable or disable multi-controller monitor
 *
 * When enabled, the bus monitor detects multiple controllers on the bus
 * and handles arbitration.
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_multi_controller_monitor_set_enabled(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ctrl.f.MULTI_CONTROLLER_MONITOR_EN = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

/**
 * @brief Enable or disable address NACK after timeout
 *
 * When enabled, target will NACK address phase if stretch timeout occurs.
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_addr_nack_set_enabled(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__CTRL_t ctrl = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ctrl.f.NACK_ADDR_AFTER_TIMEOUT = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ctrl.w);

    return I2C_OK;
}

/**
 * @brief Get current Auto ACK Counter value
 *
 * Returns the number of remaining bytes the target will automatically ACK.
 * Only valid when ACK Control Mode is enabled.
 *
 * @param idx I2C instance index
 * @param count Pointer to store counter value
 * @return I2C_OK on success, I2C_ERROR_INVALID if count is NULL
 */
int i2c_get_auto_ack_count(uint32_t idx, uint16_t *count) {
    if (!count) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ACK_CTRL_t ack_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    *count = ack_ctrl.f.NBYTES;
    return I2C_OK;
}

/**
 * @brief Set Auto ACK Counter value
 *
 * Reloads the counter with specified value. The target will automatically
 * ACK this many bytes. Only accepted if target is stretching due to
 * counter exhaustion. Requires ACK Control Mode to be enabled.
 *
 * @param idx I2C instance index
 * @param count Number of bytes to automatically ACK (0-255)
 * @return I2C_OK on success
 */
int i2c_set_auto_ack_count(uint32_t idx, uint16_t count) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ACK_CTRL_t ack_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ack_ctrl.f.NBYTES = count & 0x1FF;
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  ack_ctrl.w);

    return I2C_OK;
}

/**
 * @brief Instruct target to NACK current transaction
 *
 * Only takes effect if target is stretching due to Auto ACK Count
 * exhaustion. Requires ACK Control Mode to be enabled.
 *
 * @param idx I2C instance index
 * @return I2C_OK on success
 */
int i2c_nack_transaction(uint32_t idx) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ACK_CTRL_t ack_ctrl = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ack_ctrl.f.NACK = 1; // Set NACK bit
    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  ack_ctrl.w);

    return I2C_OK;
}

/**
 * @brief Get pending data byte when stretching
 *
 * Returns the data byte pending for ACK/NACK when target is stretching
 * due to Auto ACK Count exhaustion. Only valid when ACK Control Mode enabled.
 *
 * @param idx I2C instance index
 * @param data Pointer to store pending data byte
 * @return I2C_OK on success, I2C_ERROR_INVALID if data is NULL
 */
int i2c_get_pending_acq_byte(uint32_t idx, uint8_t *data) {
    if (!data) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);

    i2c__ACQ_FIFO_NEXT_DATA_t next_data = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQ_FIFO_NEXT_DATA_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    *data = next_data.f.DATA & 0xFF;
    return I2C_OK;
}

/**
 * @brief Enable or disable override mode
 *
 * In override mode, software can directly control SCL and SDA lines.
 * Use with i2c_override_drive_pins() and i2c_override_sample_pins().
 *
 * @param idx I2C instance index
 * @param enable true to enable, false to disable
 * @return I2C_OK on success
 */
int i2c_override_set_enabled(uint32_t idx, bool enable) {
    uint32_t base = i2c_get_base(idx);

    i2c__OVRD_t ovrd = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ovrd.f.TXOVRDEN = enable ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ovrd.w);

    return I2C_OK;
}

/**
 * @brief Drive SCL and SDA pins in override mode
 *
 * Directly controls pin values when override mode is enabled.
 *
 * @param idx I2C instance index
 * @param scl SCL pin value (true = high, false = low)
 * @param sda SDA pin value (true = high, false = low)
 * @return I2C_OK on success
 */
int i2c_override_drive_pins(uint32_t idx, bool scl, bool sda) {
    uint32_t base = i2c_get_base(idx);

    i2c__OVRD_t ovrd = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR(0) -
                                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    ovrd.f.SCLVAL = scl ? 1 : 0;
    ovrd.f.SDAVAL = sda ? 1 : 0;
    i2c_write_reg(
        base + (SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR(0) - SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
        ovrd.w);

    return I2C_OK;
}

/**
 * @brief Sample SCL and SDA pin values
 *
 * Returns the last 16 oversampled values of SCL and SDA pins.
 * Bit 0 is the most recent sample.
 *
 * @param idx I2C instance index
 * @param scl_samples Pointer to store SCL samples (may be NULL)
 * @param sda_samples Pointer to store SDA samples (may be NULL)
 * @return I2C_OK on success
 */
int i2c_override_sample_pins(uint32_t idx, uint16_t *scl_samples, uint16_t *sda_samples) {
    uint32_t base = i2c_get_base(idx);

    i2c__VAL_t val = {.w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_VAL_BASE_ADDR(0) -
                                                SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (scl_samples) {
        *scl_samples = val.f.SCL_RX;
    }

    if (sda_samples) {
        *sda_samples = val.f.SDA_RX;
    }

    return I2C_OK;
}

/**
 * @brief Set target device ID (addresses) with masks
 *
 * Configures up to two addresses that target will respond to.
 * Each address can have a mask for partial matching.
 *
 * @param idx I2C instance index
 * @param id0 First address/mask pair (may be NULL to disable)
 * @param id1 Second address/mask pair (may be NULL to disable)
 * @return I2C_OK on success
 */
int i2c_set_device_id(uint32_t idx, const i2c_target_id_t *id0, const i2c_target_id_t *id1) {
    uint32_t base = i2c_get_base(idx);

    i2c__TARGET_ID_t target_id = {.w = 0};

    if (id0) {
        target_id.f.ADDRESS0 = id0->address & 0x7F;
        target_id.f.MASK0 = id0->mask & 0x7F;
    }

    if (id1) {
        target_id.f.ADDRESS1 = id1->address & 0x7F;
        target_id.f.MASK1 = id1->mask & 0x7F;
    }

    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  target_id.w);
    return I2C_OK;
}

/**
 * @brief Read multiple bytes from RX FIFO
 *
 * Reads a chunk of bytes from the RX FIFO in controller mode.
 * This is a convenience wrapper for reading multiple received bytes.
 *
 * @param idx I2C instance index
 * @param buffer Buffer to store read bytes
 * @param size Number of bytes to read
 * @return Number of bytes actually read, or negative error code
 */
int i2c_read_bytes(uint32_t idx, uint8_t *buffer, size_t size) {
    if (!buffer || size == 0) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);
    size_t bytes_read = 0;

    for (size_t i = 0; i < size; i++) {
        // Check if RX FIFO has data
        i2c__HOST_FIFO_STATUS_t fifo_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (fifo_status.f.RXLVL == 0) {
            // No more data available
            break;
        }

        // Read byte from RX FIFO
        i2c__RDATA_t rdata = {.w =
                                  i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_RDATA_BASE_ADDR(0) -
                                                       SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        buffer[i] = rdata.f.DATA & 0xFF;
        bytes_read++;
    }

    return (int)bytes_read;
}

/**
 * @brief Write multiple raw bytes to FMT FIFO
 *
 * Writes a chunk of raw bytes with the same format flags to FMT FIFO.
 * Useful for batch operations with consistent formatting.
 *
 * @param idx I2C instance index
 * @param bytes Buffer containing bytes to write
 * @param size Number of bytes to write
 * @param flags Format flags to apply to all bytes
 * @return Number of bytes actually written, or negative error code
 */
int i2c_write_bytes_raw(uint32_t idx, const uint8_t *bytes, size_t size, uint32_t flags) {
    if (!bytes || size == 0) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);
    size_t bytes_written = 0;

    for (size_t i = 0; i < size; i++) {
        // Check if FMT FIFO has space
        i2c__HOST_FIFO_STATUS_t fifo_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (fifo_status.f.FMTLVL >= I2C_PARAM_FIFO_DEPTH) {
            // FIFO full, stop writing
            break;
        }

        // Prepare FDATA with byte and flags
        i2c__FDATA_t fdata = {.w = 0};
        fdata.f.FBYTE = bytes[i];

        // Apply flags (START, STOP, READ, etc.)
        fdata.w |= (flags & 0xFFFFFF00); // Keep upper bits as flags

        // Write to FMT FIFO
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      fdata.w);
        bytes_written++;
    }

    return (int)bytes_written;
}

/**
 * @brief Transmit multiple bytes to target TX FIFO
 *
 * Writes multiple bytes to TX FIFO for target mode responses.
 * Useful for preparing multi-byte responses to controller reads.
 *
 * @param idx I2C instance index
 * @param bytes Buffer containing bytes to transmit
 * @param size Number of bytes to transmit
 * @return Number of bytes actually written, or negative error code
 */
int i2c_transmit_bytes(uint32_t idx, const uint8_t *bytes, size_t size) {
    if (!bytes || size == 0) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);
    size_t bytes_written = 0;

    for (size_t i = 0; i < size; i++) {
        // Check if TX FIFO has space
        i2c__TARGET_FIFO_STATUS_t fifo_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (fifo_status.f.TXLVL >= I2C_PARAM_FIFO_DEPTH) {
            // FIFO full, stop writing
            break;
        }

        // Write byte to TX FIFO
        i2c__TXDATA_t txdata = {.w = 0};
        txdata.f.DATA = bytes[i];
        i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR(0) -
                              SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                      txdata.w);
        bytes_written++;
    }

    return (int)bytes_written;
}

/**
 * @brief Acquire multiple bytes from target ACQ FIFO
 *
 * Reads multiple bytes and their associated signals from ACQ FIFO.
 * Each entry includes data byte plus START/STOP/NACK signals.
 *
 * @param idx I2C instance index
 * @param buffer Array to store acquired data
 * @param size Maximum number of entries to read
 * @return Number of entries actually read, or negative error code
 */
int i2c_acquire_bytes(uint32_t idx, i2c_acq_data_t *buffer, size_t size) {
    if (!buffer || size == 0) {
        return I2C_ERROR_INVALID;
    }

    uint32_t base = i2c_get_base(idx);
    size_t entries_read = 0;

    for (size_t i = 0; i < size; i++) {
        // Check if ACQ FIFO has data
        i2c__TARGET_FIFO_STATUS_t fifo_status = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        if (fifo_status.f.ACQLVL == 0) {
            // No more data available
            break;
        }

        // Read ACQ data
        i2c__ACQDATA_t acqdata = {
            .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR(0) -
                                      SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

        // Parse ACQ data entry
        buffer[i].data = acqdata.f.ABYTE & 0xFF;
        buffer[i].signal = acqdata.f.SIGNAL & 0x7; // 3-bit signal field
        entries_read++;
    }

    return (int)entries_read;
}

/**
 * @brief Get comprehensive FIFO status for all FIFOs
 *
 * Returns the current levels of FMT, RX, TX, and ACQ FIFOs in one call.
 * Useful for monitoring overall I2C block state.
 *
 * @param idx I2C instance index
 * @param fmt_level Pointer to store FMT FIFO level (may be NULL)
 * @param rx_level Pointer to store RX FIFO level (may be NULL)
 * @param tx_level Pointer to store TX FIFO level (may be NULL)
 * @param acq_level Pointer to store ACQ FIFO level (may be NULL)
 * @return I2C_OK on success
 */
int i2c_get_all_fifo_levels(uint32_t idx, uint32_t *fmt_level, uint32_t *rx_level,
                            uint32_t *tx_level, uint32_t *acq_level) {
    uint32_t base = i2c_get_base(idx);

    // Read host FIFO status
    i2c__HOST_FIFO_STATUS_t host_status = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (fmt_level) *fmt_level = host_status.f.FMTLVL;
    if (rx_level) *rx_level = host_status.f.RXLVL;

    // Read target FIFO status
    i2c__TARGET_FIFO_STATUS_t target_status = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (tx_level) *tx_level = target_status.f.TXLVL;
    if (acq_level) *acq_level = target_status.f.ACQLVL;

    return I2C_OK;
}

/**
 * @brief Write formatted byte to FMT FIFO with explicit flags
 *
 * Writes a single byte with explicit format flags (START, STOP, READ, etc.).
 * This provides fine-grained control over transaction formatting.
 *
 * @param idx I2C instance index
 * @param byte Data byte to write
 * @param start Set START condition before byte
 * @param stop Set STOP condition after byte
 * @param read Interpret byte as read count
 * @param read_cont Continue reading (ACK last byte)
 * @param suppress_nak_irq Suppress NAK interrupt for this byte
 * @return I2C_OK on success, error code on failure
 */
int i2c_write_byte_formatted(uint32_t idx, uint8_t byte, bool start, bool stop, bool read,
                             bool read_cont, bool suppress_nak_irq) {
    uint32_t base = i2c_get_base(idx);

    // Check FIFO space
    i2c__HOST_FIFO_STATUS_t fifo_status = {
        .w = i2c_read_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR(0) -
                                  SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)))};

    if (fifo_status.f.FMTLVL >= I2C_PARAM_FIFO_DEPTH) {
        return I2C_ERROR_FIFO_FULL;
    }

    // Build FDATA with flags
    i2c__FDATA_t fdata = {.w = 0};
    fdata.f.FBYTE = byte;
    fdata.f.START = start ? 1 : 0;
    fdata.f.STOP = stop ? 1 : 0;
    fdata.f.READB = read ? 1 : 0;
    fdata.f.RCONT = read_cont ? 1 : 0;
    fdata.f.NAKOK = suppress_nak_irq ? 1 : 0;

    i2c_write_reg(base + (SMC_TOP_SMC_I2C_WRAP_I2C_FDATA_BASE_ADDR(0) -
                          SMC_TOP_SMC_I2C_WRAP_I2C_BASE_ADDR(0)),
                  fdata.w);
    return I2C_OK;
}
