/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_drbg_timeout_boundary.c
 * @brief DRBG Sampler timeout precise-boundary regression test
 *
 * Verifies that a DRBG DATA read times out after EXACTLY CFG.TIMEOUT active
 * wait cycles in StRequest/StByteAssembly, with no off-by-one extension and no
 * underflow of `timeout_cnt`.
 *
 * Method (firmware-observable, deterministic on a single-issue in-order CPU):
 *
 *   1. Configure CFG.PREFETCH=0 and CFG.TIMEOUT=N.
 *   2. With TVALID continuously asserted by the TB, measure the cycles taken
 *      by a successful DATA read.  The FSM goes
 *           StIdle -> StRequest (1 cycle, TVALID seen) -> StRespond (1) -> R.
 *   3. Stop the TB (`tb_drbg_stop`), drain the residual in-flight beat, then
 *      measure the cycles taken by a timing-out DATA read.  The FSM goes
 *           StIdle -> StRequest (N cycles) -> StTimeout (1) -> R.
 *   4. Difference of the two measurements = (N + 3) - (4) = N - 1 cycles.
 *      All other latency (AXI fabric, PicoRV32 LSU, TB_CMD round-trip) is
 *      identical in both measurements and cancels in the subtraction, so the
 *      difference is exact.
 *
 * Defect guarded against (off-by-one):
 *   A `timeout_cnt` loaded to N with a non-saturating decrement and firing on
 *   `cnt == 0` keeps the FSM in StRequest for N+1 active cycles and
 *   underflows to 0xFFFF on the terminal cycle.  The RTL loads `cnt` with
 *   N-1, decrements saturatingly and fires on `cnt == 0`, giving exactly N
 *   active cycles.  The observed difference is N - 1, or N under the defect,
 *   so the assertion fails by exactly one cycle if the defect is present.
 *
 * Run with:
 *   make run_fw FW_TEST=test_drbg_timeout_boundary
 */

#include "test_common.h"
#include "key_manager_fw.h"
#include "key_manager_addr.h"

#define DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)
#define DRBG_CFG_REG \
    (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)
#define DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)

/* Use a moderate timeout: large enough that a 1-cycle bug is unambiguous,
 * small enough that the test simulates quickly. */
#define BOUNDARY_TIMEOUT_CYCLES 50u

/* Clear DRBG STATUS sticky bits (W1C) so a measurement starts cleanly. */
static void clear_drbg_sticky_status(void) {
    km_drbg_sampler__status_reg_t w1c = {0};
    w1c.f.timeout_err = 1;
    w1c.f.stream_err = 1;
    DRBG_STATUS_REG.w = w1c.w;
}

/**
 * @brief Measure the firmware-observable cycle count of a single DATA read.
 *
 * @return Cycles elapsed between two `tb_get_cycle_count` snapshots that
 *         bracket exactly one `(void)DRBG_DATA_REG.f.data;` access.
 */
static uint32_t measure_data_read_cycles(void) {
    uint32_t t_start;
    uint32_t t_end;

    if (!tb_get_cycle_count(&t_start, 1000u)) {
        TEST_FAIL("tb_get_cycle_count(start) failed");
    }
    (void)DRBG_DATA_REG.f.data;
    if (!tb_get_cycle_count(&t_end, 1000u)) {
        TEST_FAIL("tb_get_cycle_count(end) failed");
    }
    return t_end - t_start;
}

int main(void) {
    uint32_t delta_success;
    uint32_t delta_timeout;
    uint32_t observed_diff;
    uint32_t expected_diff;

    TEST_INIT();

    /* Bound total simulation time conservatively (each measurement is < 200
     * cycles, plus TB_CMD round-trips). */
    if (!tb_set_timeout(50000u)) {
        TEST_FAIL("tb_set_timeout failed");
    }

    /* Deterministic DRBG payload so the successful read returns a stable
     * value. */
    if (!tb_drbg_set_seed(1u, 1000u)) {
        TEST_FAIL("tb_drbg_set_seed failed");
    }

    DRBG_CFG_REG.w = 0u;
    DRBG_CFG_REG.f.prefetch = 0u;
    DRBG_CFG_REG.f.timeout = (uint16_t)BOUNDARY_TIMEOUT_CYCLES;
    clear_drbg_sticky_status();

    /*-----------------------------------------------------------------------
     * Subtest 1: baseline successful read (TVALID asserted by TB driver).
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("DRBG DATA read baseline (TVALID immediate)");
    delta_success = measure_data_read_cycles();
    if (DRBG_STATUS_REG.f.timeout_err != 0u) {
        TEST_FAIL("Baseline read unexpectedly set TIMEOUT_ERR (delta=%u)", (unsigned)delta_success);
    }
    if (DRBG_STATUS_REG.f.count_good == 0u) {
        TEST_FAIL("Baseline read did not increment COUNT_GOOD (delta=%u)", (unsigned)delta_success);
    }
    TEST_LOG("  baseline delta=%u cycles", (unsigned)delta_success);
    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Stop the TB driver.  Per AXI-Stream rules the TB completes the next
     * beat (TVALID held until TREADY) then deasserts TVALID and stays
     * stopped until tb_drbg_start().  The first read after STOP consumes
     * that residual beat (so it succeeds); subsequent reads time out.
     *-----------------------------------------------------------------------*/
    if (!tb_drbg_stop(1000u)) {
        TEST_FAIL("tb_drbg_stop failed");
    }
    (void)DRBG_DATA_REG.f.data; /* drain the residual beat */
    if (DRBG_STATUS_REG.f.timeout_err != 0u) {
        TEST_FAIL("Drain read unexpectedly set TIMEOUT_ERR");
    }
    clear_drbg_sticky_status();

    /*-----------------------------------------------------------------------
     * Subtest 2: timing-out read with the same firmware code path.
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("DRBG DATA read timeout (TVALID stalled)");
    delta_timeout = measure_data_read_cycles();
    if (DRBG_STATUS_REG.f.timeout_err == 0u) {
        TEST_FAIL("Timeout read failed to set TIMEOUT_ERR (delta=%u)", (unsigned)delta_timeout);
    }
    if (DRBG_STATUS_REG.f.count_bad == 0u) {
        TEST_FAIL("Timeout read failed to increment COUNT_BAD (delta=%u)", (unsigned)delta_timeout);
    }
    TEST_LOG("  timeout  delta=%u cycles", (unsigned)delta_timeout);
    TEST_SUBTEST_PASS();

    /*-----------------------------------------------------------------------
     * Subtest 3: precise-boundary check.
     *
     * FSM cycle accounting (AR -> R-consume):
     *   success:           StRequest(1) + StRespond(1) + slot_done(1) + AR_latch(1) = 4
     *   timeout:           StRequest(N) + StTimeout(1) + slot_done(1) + AR_latch(1) = N + 3
     *   timeout (defect):  StRequest(N+1) + StTimeout(1) + slot_done(1) + AR_latch(1) = N + 4
     *
     * delta_timeout - delta_success therefore equals (N - 1), or (N) under
     * the off-by-one defect, regardless of constant fabric/firmware overhead
     * which cancels in the subtraction.
     *-----------------------------------------------------------------------*/
    TEST_SUBTEST_START("DRBG StTimeout fires at programmed CFG.TIMEOUT boundary");
    if (delta_timeout < delta_success) {
        TEST_FAIL("Timeout cycles (%u) < baseline cycles (%u): instrumentation bug",
                  (unsigned)delta_timeout, (unsigned)delta_success);
    }
    observed_diff = delta_timeout - delta_success;
    expected_diff = (uint32_t)(BOUNDARY_TIMEOUT_CYCLES - 1u);
    if (observed_diff != expected_diff) {
        TEST_FAIL("DRBG timeout boundary off-by-one: CFG.TIMEOUT=%u "
                  "baseline=%u timeout=%u observed_diff=%u expected_diff=%u "
                  "(timeout fired %d cycle(s) %s)",
                  (unsigned)BOUNDARY_TIMEOUT_CYCLES, (unsigned)delta_success,
                  (unsigned)delta_timeout, (unsigned)observed_diff, (unsigned)expected_diff,
                  (int)((int32_t)observed_diff - (int32_t)expected_diff),
                  (observed_diff > expected_diff) ? "late" : "early");
    }
    TEST_LOG("  CFG.TIMEOUT=%u observed_diff=%u expected_diff=%u (OK)",
             (unsigned)BOUNDARY_TIMEOUT_CYCLES, (unsigned)observed_diff, (unsigned)expected_diff);
    TEST_SUBTEST_PASS();

    /* Restart TB driver so any subsequent diagnostic reads do not block. */
    if (!tb_drbg_start(1000u)) {
        TEST_FAIL("tb_drbg_start failed");
    }

    TEST_PASS();
    return 0;
}
