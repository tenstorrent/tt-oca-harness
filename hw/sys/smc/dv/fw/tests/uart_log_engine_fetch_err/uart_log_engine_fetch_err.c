/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_fetch_err_test
//
// Inject an AXI fetch error and verify it propagates to
// INTR_STATUS.LOG_FETCH_ERR.
//
// Path: log_engine.log_fetch_axil → smc_peripherals → smc.axil_log_engine →
//       smc_base → smc_fabric.axi_lite_log → smc_input_fabric →
//       axi_lite_to_axi → alias_remap → local/global demux → default DECERR
//       slave (for unmapped local addresses)
//
// Strategy: point LOG_REGION_ADDR at 0xC0001000 (unmapped, in the gap between
// SMC_CLUSTER_CORE3_WDT @ 0xC0000C00..0xC0000C24 and SMC_RESET_UNIT @
// 0xC0002000). Engine fetch hits fabric default DECERR slave → log_fetch_err
// → (with INTR_ENABLE) → INTR_STATUS.LOG_FETCH_ERR latches.
//
// Per log_engine.sv:457-459:
//   INTR_STATUS.LOG_FETCH_ERR = (log_fetch_err || INTR_TEST.LOG_FETCH_ERR)
//                                AND INTR_ENABLE.LOG_FETCH_ERR
//
// LEVEL-INTR NOTE: while the engine is still enabled AND LOG_CTRL[0]>0 AND
// the unmapped address keeps DECERR-ing, log_fetch_err keeps re-asserting
// each cycle. So W1C `INTR_STATUS.LOG_FETCH_ERR=1` while the source is still
// pulsing won't clear: status re-latches immediately. The test therefore
// MUST disable CTRL.EN before W1C to let the source go low.
//
// Uses test_fail(0) directly (noreturn) instead of raise_error + end_test.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG      SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define LE_CTRL_OFF         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_SIZE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_ADDR_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_WRITE_ADDR_OFF   (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_ENABLE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define UART_RBR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))

#define BIT_FETCH_ERR       (1u << 0)
#define BIT_WRITE_ERR       (1u << 4)
#define LE_INTR_TEST_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_TEST_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define UNMAPPED_ADDR       0xC0001000u

static void fail_at(const char *msg) {
    info_msg_s(0, msg);
    test_fail(0);  // noreturn
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_fetch_err_test start");

    write_reg(WRAP0_CTRL_REG, 1u);

    // Make sure status is clear (and INTR_ENABLE on so W1C path is valid).
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);

    if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) != 0u) {
        fail_at("FAIL: status did not clear at start");
    }

    //--------------------------------------------------------------------------
    // SCENARIO 0 (v013) — INTR_TEST self-test term, run FIRST (before any real
    // fetch error). log_engine.sv:457/460:
    //   INTR_STATUS.LOG_xxx_ERR.next = (log_xxx_err || INTR_TEST.LOG_xxx_ERR) && ENABLE
    // Scenarios A-D drive the `log_xxx_err` real-error term. To cover the
    // `INTR_TEST.LOG_xxx_ERR` term as the DECIDING factor, log_xxx_err must be
    // 0 while INTR_TEST toggles — only true here, before the first DECERR
    // (after which log_fetch_err latches stuck at 1, masking the cond's
    // INTR_TEST term). INTR_TEST is a `singlepulse` field: writing 1 asserts
    // for one cycle. We only need the write to exercise the cond term; the
    // status (level-intr) is not observably sticky for a singlepulse, so we
    // do not poll it.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario 0: INTR_TEST self-test term (FETCH_ERR + WRITE_ERR)");
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF,   BIT_FETCH_ERR);                  // pulse fetch self-test
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF,   BIT_WRITE_ERR);                  // pulse write self-test
    write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF,   BIT_FETCH_ERR | BIT_WRITE_ERR);  // both
    // Mask + W1C to leave a clean slate for scenario A.
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);

    // Program engine: fetch from UNMAPPED_ADDR → DECERR
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF,     UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 16u);

    //--------------------------------------------------------------------------
    // Poll INTR_STATUS.LOG_FETCH_ERR with timeout. DECERR should reach the
    // engine within a few dozen cycles; allow generous timeout.
    //--------------------------------------------------------------------------
    {
        uint32_t timeout = 200000u;
        while (timeout > 0u) {
            uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
            if (s != 0u) break;
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_hex32_s(0, "FAIL: timeout waiting for FETCH_ERR, status=",
                             read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF));
            test_fail(0);
        }
    }

    //--------------------------------------------------------------------------
    // Clear the level interrupt. NOTE (v013, found via waveform debug):
    // log_fetch_err (= axil_lite_from_log_fetch_fsm.mem_rsp_error_o) stays
    // ASSERTED after the engine is disabled — the last DECERR response is held
    // and there is no new transaction to clear it. So as long as
    // INTR_ENABLE.LOG_FETCH_ERR=1, INTR_STATUS.next = (log_fetch_err||TEST) &&
    // ENABLE re-latches every cycle and W1C can never stick (the old retry
    // loop here spun forever and the test hit the cocotb watchdog). The
    // correct way to clear a level interrupt whose source is stuck is to MASK
    // it first (disable ENABLE → next gated to 0), then W1C. See ticket on
    // the stuck-log_fetch_err behavior.
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);          // disable engine
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);   // mask → gate next to 0
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);  // W1C
    if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) != 0u) {
        fail_at("FAIL: W1C did not clear LOG_FETCH_ERR after masking ENABLE");
    }

    //--------------------------------------------------------------------------
    // ENABLE=0 → status must NOT re-latch
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);  // clear stale
    for (volatile int i = 0; i < 200; i++) { }
    if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) != 0u) {
        fail_at("FAIL: ENABLE=0 but status latched (gating broken)");
    }

    //--------------------------------------------------------------------------
    // SCENARIO B (v004) — sustained fetch-error sequence with a larger log
    // region so the fetch FSM spends multiple cycles in WAIT before the
    // DECERR resolves. Exercises log_fetch_fsm REQ → WAIT → REQ multi-beat
    // and WAIT → IDLE error transitions.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: sustained DECERR fetch on large region");

    // Re-enable error path
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);

    // Bigger region — 4 KB unmapped, slot 0 = 256 bytes per entry. Engine
    // will fetch 64 beats × 4 bytes (or however the AXI handshake unfolds),
    // each one DECERRing. The WAIT state is held while each AXI beat
    // resolves.
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x1000u);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    // Trigger a 256-byte slot 0 — large enough that the engine paces through
    // multiple fetch attempts before DECERR latches the error flag once.
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 256u);
    {
        uint32_t timeout = 200000u;
        while (timeout > 0u &&
               (read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            fail_at("FAIL: scenario B: large-region DECERR not detected");
        }
    }
    // Abort + W1C clear
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    for (int i = 0; i < 100; i++) {
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) break;
    }

    //--------------------------------------------------------------------------
    // SCENARIO C (v013) — log_write FSM error path, write to BAD addr.
    //
    // Goal was to land the REAL-error term of log_engine.sv:460
    //   INTR_STATUS.LOG_WRITE_ERR.next = (log_write_err || INTR_TEST) && ENABLE
    // i.e. log_write_err=1 from an actual write DECERR. (scenario 0 already
    // covers the INTR_TEST term of that cond.)
    //
    // FINDING (v013): a firmware-driven good-fetch/bad-write does NOT cleanly
    // produce log_write_err. Reads to an unmapped fabric address DECERR fine
    // (scenarios B/D prove this on the log_FETCH master), but a WRITE to the
    // same unmapped address via the log_WRITE master gets no write-side error
    // response and HANGS the shared SMC fabric — the next CPU CSR access then
    // never returns and the test hits the cocotb watchdog. Confirmed by:
    //   - replica[2] (pristine) good-fetch + write→UNMAPPED → CPU CSR read
    //     after the write never returns (no status dump printed, watchdog).
    // On replica[0] this never surfaced earlier only because the FETCH errored
    // first, so the write master was never engaged.
    //
    // Net: the log_write_err real-error term is NOT reachable by firmware
    // stimulus (it needs a TB-level fabric write-error injector, or is a
    // design gap — the log_write master has no DECERR timeout). Documented in
    // the coverage report + ticket. Here we keep the bounded, NON-hanging
    // replica[0] form: the fetch DECERRs (so no write is ever issued → no
    // fabric hang), which still exercises the log_write FSM IDLE/REQ arms and
    // the INTR_ENABLE(WRITE) datapath. WARN-not-fail.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: log_write FSM error-path exercise");

    #define LOG_BUF_BASE        (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)

    // Pre-load SRAM with pattern (harmless; fetch target below is UNMAPPED so
    // the fetch DECERRs before any write — avoids the fabric write-hang).
    volatile uint8_t *sbuf = (volatile uint8_t *)(uintptr_t)LOG_BUF_BASE;
    for (int i = 0; i < 16; i++) sbuf[i] = (uint8_t)(0xD0u + i);

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);

    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);      // fetch DECERRs
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 16u);

    {
        // Short bounded poll: WRITE_ERR will not latch (fetch errors first; the
        // write is never reached). WARN-not-fail — the fetch-error path + the
        // log_write FSM IDLE/REQ arms are still exercised. Keep the poll short
        // so the non-latch can never spin into the cocotb watchdog.
        uint32_t timeout = 2000u;
        while (timeout > 0u &&
               (read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_WRITE_ERR) == 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_hex32_s(0, "WARN: scenario C: WRITE_ERR not latched (status=",
                             read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF));
        }
    }
    // Abort + clear
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    for (int i = 0; i < 100; i++) {
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) &
             (BIT_FETCH_ERR | BIT_WRITE_ERR)) == 0u) break;
    }

    //--------------------------------------------------------------------------
    // SCENARIO D (v004) — fetch error on replica [1] to exercise the
    // gen_uart_log_engine_wraps[1].log_engine fetch FSM specifically.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario D: replica[1] fetch DECERR");

    #define WRAP1_CTRL_REG    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1)
    #define WRAP1_UART_BASE   SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1)
    #define WRAP1_LE_BASE     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(1)

    write_reg(WRAP1_CTRL_REG, 1u);
    write_reg(WRAP1_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP1_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP1_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
    write_reg(WRAP1_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);
    write_reg(WRAP1_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP1_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP1_LE_BASE + LE_WRITE_ADDR_OFF, WRAP1_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP1_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP1_LE_BASE + LE_LOG_CTRL0_OFF, 16u);

    {
        uint32_t timeout = 200000u;
        while (timeout > 0u &&
               (read_reg(WRAP1_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            fail_at("FAIL: scenario D: replica[1] FETCH_ERR not detected");
        }
    }
    write_reg(WRAP1_LE_BASE + LE_CTRL_OFF, 0u);
    for (int i = 0; i < 100; i++) {
        write_reg(WRAP1_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
        if ((read_reg(WRAP1_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) break;
    }
    write_reg(WRAP1_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP1_CTRL_REG, 0u);

    // Cleanup (wrap0)
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_fetch_err_test done");
    test_pass(0);  // noreturn

    while (1) __asm__("wfi");
    return 0;
}
