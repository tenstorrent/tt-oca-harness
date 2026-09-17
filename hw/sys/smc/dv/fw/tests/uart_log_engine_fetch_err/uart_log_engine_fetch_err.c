/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_fetch_err_test
//
// Inject an AXI fetch error and verify it propagates to
// INTR_STATUS.LOG_FETCH_ERR.
//
// Path: log_engine.log_fetch_axil -> smc_peripherals -> smc.axil_log_engine ->
//       smc_base -> smc_fabric.axi_lite_log -> smc_input_fabric ->
//       axi_lite_to_axi -> alias_remap -> local/global demux -> default DECERR
//       slave (for unmapped local addresses)
//
//==========================================================================
// EXPECTED MODEL -- SOURCES
//==========================================================================
// Every expectation asserted below is derived from the register spec, not
// from the RTL that implements it. Sources:
//
//   [S1] hw/ip/uart/log_engine/regs/log_engine.rdl
//        @ revision ffc8cdcc3 ("hw: Reorganize hw/ip and hw/common taxonomy")
//   [S2] hw/sys/smc/regs/gen/c/smc_addr.h (generated SMC address map)
//
// From [S1]:
//   INTR_STATUS @0x14 -- LOG_FETCH_ERR[0], LOG_WRITE_ERR[4].
//       sw=rw, hw=w, `level intr`, `woclr`.  So: hardware SETS the bit while
//       its cause is asserted; software clears by writing 1 (W1C); and
//       because the interrupt is `level`, a bit cleared while its cause is
//       STILL asserted is set again immediately.  [S1]:64-83
//   INTR_ENABLE @0x18 -- same bit positions, RW.  [S1]:85-98
//   INTR_TEST  @0x1C -- same bit positions, sw=w, `singlepulse`: "Writing `1`
//       forces the interrupt", asserted for exactly one cycle.  [S1]:100-116
//   LOG_CTRL[i] @0x40+4i -- LOG_LEN[15:0], RW + `hwclr`.  Writing a nonzero
//       length starts the transfer for that entry; hardware clears the field
//       when the transfer completes.  A LOG_CTRL entry that reads back 0 is
//       therefore the DUT's own statement that the transfer finished, and one
//       that reads back nonzero is its statement that it did not.  [S1]:118-128
//
// INTR_ENABLE SEMANTICS:
//   INTR_ENABLE masks irq_o only.  INTR_STATUS latches whether or not the
//   interrupt is enabled and is cleared only by W1C, as prim_intr_hw does, so
//   an event that arrives while masked is held, not lost.  The two mask arms
//   in scenario 0b check exactly that: an INTR_TEST pulse sets the status bit
//   with ENABLE=1 and again with ENABLE=0, and a W1C clears it with ENABLE
//   still 0.
//
//==========================================================================
// ERROR-EVENT SEMANTICS AND HOW THIS TEST CLEARS A LATCHED ERROR
//==========================================================================
// log_engine.sv qualifies the fetch master's response error with the
// response strobe, so each errored beat is a one-cycle event that INTR_STATUS
// latches (`level intr` + `woclr`, [S1]) and a W1C retires.  Two consequences
// for the scenarios below:
//
//   1. A RUNNING engine pointed at an unmapped region keeps issuing fetches,
//      so DECERR events keep arriving and a W1C cannot stick until CTRL.EN is
//      cleared.  Every scenario therefore stops the engine before it clears,
//      and the clear is PROVEN by reading back 0 (clear_intr_or_fail).
//
//   2. TO MAKE A LATER SCENARIO'S POLL MEAN ANYTHING: the clear is proven to
//      HOLD over a settle window (assert_fetch_err_retired), otherwise the
//      next scenario's poll would again be reading the PREVIOUS scenario's
//      error and would return on its first iteration whether or not the new
//      stimulus did anything at all.  A good fetch out of SPM is run first
//      (retire_fetch_err) to show the engine recovers after an aborted fetch.
//
//
// Failures call test_fail(0) (noreturn).

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define LE_CTRL_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_SIZE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_ADDR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_WRITE_ADDR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_ENABLE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_TEST_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_TEST_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define UART_RBR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IER_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IIR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LCR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MCR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))

/* Field bit positions.  Source: [S2] section "Region 3: Log Engine" tables for
 * INTR_STATUS / INTR_ENABLE / INTR_TEST @ revision 9fe804d, which match
 * [S1] log_engine.rdl:64-116 (LOG_FETCH_ERR[0:0], LOG_WRITE_ERR[4:4]).
 * No generated field header exists for log_engine yet
 * (hw/sys/smc/regs/gen/c/blocks/ contains none); replace these two masks with
 * generated field symbols as soon as the log_engine RDL C export lands. */
#define BIT_FETCH_ERR (1u << 0)
#define BIT_WRITE_ERR (1u << 4)
#define LOG_LEN_MASK 0xFFFFu /* LOG_CTRL.LOG_LEN[15:0], [S1]:118-128 */

/* Unmapped SMC-local fabric address, DERIVED from the generated map [S3]
 * rather than hand-written: the first 4 KB-aligned address past the end of the
 * WDT cluster.  A fetch here reaches the fabric default DECERR slave. */
#define WDT_REGION_END \
    (SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR + SMC_TOP_SMC_CLUSTER_CORE3_WDT_SIZE)
#define UNMAPPED_ADDR (((WDT_REGION_END) + 0xFFFu) & ~0xFFFu)
#define UNMAPPED_SPAN 0x1000u /* largest region any scenario below programs */

/* The whole span this test points the engine at must lie strictly inside the
 * gap between the WDT cluster and the reset unit.  If the map is regenerated
 * so the gap moves or closes, this fails the build instead of silently
 * turning the DECERR scenarios into accesses to a real slave. */
_Static_assert(UNMAPPED_ADDR >= WDT_REGION_END,
               "UNMAPPED_ADDR must start at or after the end of the WDT region");
_Static_assert(UNMAPPED_ADDR + UNMAPPED_SPAN <= SMC_TOP_SMC_RESET_UNIT_BASE_ADDR,
               "UNMAPPED_ADDR + span must end at or before the reset unit base");

/* Scratch region used for the SUCCESSFUL fetch that proves the engine recovers
 * from an aborted one.  Real, mapped SPM. */
#define LOG_BUF_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)
#define GOOD_REGION_SIZE 0x100u /* 256 B region -> slot 0 spans 16 B */
#define GOOD_XFER_LEN 16u       /* == UART FIFO depth, so loopback cannot overrun */

/* Settle window for the mask, event and clear-holds arms.
 * Each iteration is a full CPU read across the AXI-Lite fabric to the log
 * engine CSR block, so RELATCH_POLLS samples span far more engine clocks than
 * the single cycle in which `level intr` capture would occur ([S1]).  Bounded
 * so a never-latching source fails instead of spinning. */
#define RELATCH_POLLS 2000u

static void fail_at(const char *msg) {
    info_msg_s(0, msg);
    test_fail(0); // noreturn
}

/* Evidence tokens + completeness gate.
 *
 * Every proven expectation emits exactly one `CHK-<NAME>:` line naming what
 * was observed against what was expected, and bumps a counter.  main() refuses
 * to pass unless the counter matches EXPECTED_CHK_COUNT exactly, so a run that
 * reached test_pass() after only a PREFIX of the scenarios -- or one where a
 * scenario was edited out -- fails instead of being recorded as a pass.  The
 * console prints go out over simputs (sim.log) where the cocotb layer cannot
 * intercept them, so the gate has to live here, in the same execution as the
 * checks it is counting.
 *
 * Keep EXPECTED_CHK_COUNT in step with the chk_ok() call sites below. */
#define EXPECTED_CHK_COUNT 16u
static uint32_t chk_count;

static void chk_ok(const char *line) {
    info_msg_s(0, line);
    chk_count++;
}

/* Clear level-interrupt status bits and PROVE they cleared.
 *
 * Only valid once the engine is stopped (or the cause was a self-retiring
 * INTR_TEST pulse): a running engine on an unmapped region keeps producing
 * DECERR events, and INTR_ENABLE cannot help because it masks irq_o, not the
 * capture.  W1C, then read back and FAIL if anything survived.  Finally set
 * INTR_ENABLE to the requested mask.
 */
static void clear_intr_or_fail(uint64_t le_base, uint32_t bits, uint32_t restore_enable,
                               const char *where) {
    write_reg(le_base + LE_INTR_STATUS_OFF, bits); /* W1C */
    uint32_t left = read_reg(le_base + LE_INTR_STATUS_OFF) & bits;
    if (left != 0u) {
        info_msg_hex32_s(0, "FAIL: W1C left status bits set, mask=", left);
        fail_at(where);
    }
    write_reg(le_base + LE_INTR_ENABLE_OFF, restore_enable);
}

/* Configure UART0 so the log engine's writes can actually drain, which is what
 * lets a good fetch run to completion.  Divisor 1 (fastest), 8N1, FIFOs on,
 * MCR.LOOP=1 so TX is consumed internally and no pad traffic is required. */
static void setup_uart_for_log_writes(void) {
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u); /* DLAB=1 */
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u); /* DLL = 1 */
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u); /* DLM = 0 */
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u); /* DLAB=0, 8 data bits */
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u); /* LOOP = 1 */
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u); /* FCR: FIFOs enabled */
}

/* Show the engine recovers after an aborted fetch: run one real 16-byte
 * transfer out of SPM into the UART and require it to complete.
 *
 * Completion is observed from the DUT, not assumed: LOG_CTRL[0].LOG_LEN is
 * `hwclr` ([S1]:118-128), so hardware zeroing it is the engine's own statement
 * that a fetch/write pair actually succeeded.  Bounded; expiry fails the test.
 */
static void retire_fetch_err(void) {
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, GOOD_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUF_BASE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, GOOD_XFER_LEN);

    uint32_t t = 2000000u;
    while (t > 0u && (read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF) & LOG_LEN_MASK) != 0u) {
        t--;
    }
    if (t == 0u) {
        info_msg_hex32_s(0, "FAIL: good fetch never completed, LOG_CTRL[0]=",
                         read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF) & LOG_LEN_MASK);
        test_fail(0);
    }
    chk_ok("CHK-GOOD-FETCH-COMPLETES: LOG_CTRL[0] hwclr observed 0x0 "
           "(expected 0x0 per LOG_CTRL.LOG_LEN hwclr)");
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
}

/* Prove the fetch-error status is genuinely clear.
 *
 * Clear, then require the bit to STAY 0 over the full settle window.  A still-
 * running errored fetch could not produce this observation: it would re-latch
 * the bit on its next beat.  This is what gives the scenario that follows a
 * baseline it has proven, so its own poll can only be satisfied by its own
 * stimulus.
 */
static void assert_fetch_err_retired(const char *where) {
    clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR, BIT_FETCH_ERR, where);
    for (uint32_t i = 0; i < RELATCH_POLLS; i++) {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: LOG_FETCH_ERR did not stay clear, status=", s);
            fail_at(where);
        }
    }
    chk_ok("CHK-FETCH-ERR-RETIRED: INTR_ENABLE=1, INTR_STATUS.LOG_FETCH_ERR "
           "observed 0x0 on every sample (expected 0x0)");
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_fetch_err_test start");

    write_reg(WRAP0_CTRL_REG, 1u);
    setup_uart_for_log_writes();

    /* Seed the SPM region used by every good fetch below. */
    volatile uint8_t *sbuf = (volatile uint8_t *)(uintptr_t)LOG_BUF_BASE;
    for (uint32_t i = 0; i < GOOD_XFER_LEN; i++) sbuf[i] = (uint8_t)(0xD0u + i);

    // Make sure status is clear.
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);

    if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) != 0u) {
        fail_at("FAIL: status did not clear at start");
    }

    //--------------------------------------------------------------------------
    // SCENARIO 0 — INTR_TEST, run FIRST (before any real fetch error).
    //
    // [S1]:100-116 specifies INTR_TEST as `singlepulse`, "Writing `1` forces
    // the interrupt", and [S1]:64-83 specifies INTR_STATUS as `level intr` +
    // `woclr`.  So a one-cycle INTR_TEST pulse must SET the corresponding
    // status bit, and because the cause self-retires after that cycle the bit
    // is then plainly clearable by W1C.  That expectation is observable, and
    // scenario 0 observes it rather than only stimulating.
    //
    // Running first matters: INTR_TEST is the only fetch/write error cause
    // this firmware can raise AND retire on demand, so it is also the cleanest
    // available control for the INTR_ENABLE mask arms in scenario 0b.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario 0: INTR_TEST self-test term (FETCH_ERR + WRITE_ERR)");
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR | BIT_WRITE_ERR, BIT_FETCH_ERR | BIT_WRITE_ERR,
                       "FAIL: scenario 0 could not start from a clear status");

    {
        struct {
            uint32_t pulse;
            const char *name;
        } const cases[3] = {
            {BIT_FETCH_ERR, "CHK-INTR-TEST-FETCH"},
            {BIT_WRITE_ERR, "CHK-INTR-TEST-WRITE"},
            {BIT_FETCH_ERR | BIT_WRITE_ERR, "CHK-INTR-TEST-BOTH"},
        };
        for (uint32_t c = 0; c < 3u; c++) {
            write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, cases[c].pulse);
            uint32_t s =
                read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & (BIT_FETCH_ERR | BIT_WRITE_ERR);
            if (s != cases[c].pulse) {
                info_msg_s(0, cases[c].name);
                info_msg_hex32_s(0, "FAIL: INTR_TEST pulse, expected status=", cases[c].pulse);
                info_msg_hex32_s(0, "                        observed status=", s);
                test_fail(0);
            }
            chk_ok(cases[c].name);
            info_msg_hex32_s(0, "  observed == expected INTR_STATUS = ", s);
            /* The singlepulse cause has already self-retired, so a plain W1C
             * must stick here; clear_intr_or_fail proves it did. */
            clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR | BIT_WRITE_ERR,
                               BIT_FETCH_ERR | BIT_WRITE_ERR,
                               "FAIL: scenario 0 status would not clear after INTR_TEST pulse");
        }
    }

    //--------------------------------------------------------------------------
    // SCENARIO 0b — INTR_ENABLE masks irq_o only; INTR_STATUS captures while
    // masked.  Checked with the controlled INTR_TEST cause.
    //
    // Both arms use the same cause in the same window, so neither can pass on
    // a dead source: the ENABLE=1 arm proves an INTR_TEST pulse does set the
    // bit here and now, and only then does the ENABLE=0 arm's "also sets" mean
    // capture-while-masked rather than a stale bit.  The masked arm then
    // proves the W1C path does not depend on the enable either.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario 0b: INTR_ENABLE masks the output, not INTR_STATUS capture");
    { /* enabled arm: ENABLE=1 -> an INTR_TEST pulse must set the bit */
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
        write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR);
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
        if (s != BIT_FETCH_ERR) {
            info_msg_hex32_s(0, "FAIL: ENABLE=1 INTR_TEST pulse did not set status, observed=", s);
            test_fail(0);
        }
        chk_ok("CHK-CAPTURE-ENABLED: ENABLE=1 + INTR_TEST pulse -> "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x1 (expected 0x1)");
    }
    { /* masked arm: ENABLE=0 -> the same pulse must ALSO set the bit, and a
       * W1C with ENABLE still 0 must clear it */
        clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR, 0u,
                           "FAIL: could not clear before the ENABLE=0 capture arm");
        write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR);
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
        if (s != BIT_FETCH_ERR) {
            info_msg_hex32_s(0, "FAIL: ENABLE=0 INTR_TEST pulse was lost, status=", s);
            fail_at("FAIL: INTR_STATUS must capture while masked (INTR_ENABLE masks "
                    "irq_o only)");
        }
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR); /* W1C, ENABLE=0 */
        for (uint32_t i = 0; i < RELATCH_POLLS; i++) {
            uint32_t r = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
            if (r != 0u) {
                info_msg_hex32_s(0, "FAIL: W1C with ENABLE=0 did not stick, status=", r);
                fail_at("FAIL: W1C must clear a masked, self-retired cause");
            }
        }
        chk_ok("CHK-CAPTURE-MASKED: ENABLE=0 + INTR_TEST pulse -> "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x1 (expected 0x1), then W1C with "
               "ENABLE=0 observed 0x0 on every sample (expected 0x0)");
    }

    //--------------------------------------------------------------------------
    // SCENARIO A — real fetch DECERR on a 256-byte unmapped region.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario A: fetch DECERR on unmapped region");
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR, BIT_FETCH_ERR,
                       "FAIL: scenario A could not start from a clear status");

    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, GOOD_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, GOOD_XFER_LEN);

    {
        uint32_t timeout = 200000u;
        while (timeout > 0u &&
               (read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_hex32_s(0, "FAIL: timeout waiting for FETCH_ERR, status=",
                             read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF));
            test_fail(0);
        }
        chk_ok("CHK-FETCH-DECERR-LATCHES: unmapped fetch -> "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x1 (expected 0x1)");
    }

    /* Event arm on the REAL source.
     *
     * Scenario 0b used an INTR_TEST pulse, which proves the capture path is
     * live but says nothing about log_fetch_err itself.  Stop the engine so no
     * further DECERR beat can arrive, W1C, and require the bit to STAY 0: the
     * error was an event that the status bit latched, not a level the fetch
     * master holds (see the semantics note at the top).  Without stopping the
     * engine first this clear could not hold, which is what the retire-and-
     * prove step before scenario B relies on. */
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    {
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR); /* W1C */
        for (uint32_t i = 0; i < RELATCH_POLLS; i++) {
            uint32_t r = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
            if (r != 0u) {
                info_msg_hex32_s(0, "FAIL: LOG_FETCH_ERR re-latched with the engine stopped, "
                                    "status=", r);
                fail_at("FAIL: log_fetch_err is behaving as a level, not an event");
            }
        }
        chk_ok("CHK-FETCH-ERR-IS-EVENT: engine stopped, W1C -> "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x0 on every sample (expected 0x0)");
    }

    //--------------------------------------------------------------------------
    // SCENARIO B — sustained fetch-error sequence over a 4 KB region so the
    // fetch FSM spends multiple cycles in WAIT before each DECERR resolves.
    //
    // Run a good fetch first to show the engine recovers after scenario A's
    // aborted fetch, then PROVE the status is clear and stays clear, so the
    // poll below can only be satisfied by scenario B's own DECERR.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: sustained DECERR fetch on large region");

    retire_fetch_err();
    assert_fetch_err_retired("FAIL: scenario B could not start from a clear LOG_FETCH_ERR");

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, UNMAPPED_SPAN);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    /* 256-byte slot 0 — long enough that the engine paces through many fetch
     * attempts rather than erroring on a single short burst. */
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
        chk_ok("CHK-LARGE-REGION-DECERR: from a proven-clear status, the 4 KB "
               "unmapped region set INTR_STATUS.LOG_FETCH_ERR to 0x1 "
               "(expected 0x1)");
    }
    {
        /* Scenario-B-specific DUT state.  LOG_CTRL.LOG_LEN is `hwclr`
         * ([S1]:118-128) and hardware zeroed it for the good fetch above
         * (CHK-GOOD-FETCH-COMPLETES).  Scenario B's transfer aborts on the
         * DECERR, so no write completes and the length written here must
         * still be standing.  A zero here would mean the 256-byte transfer
         * actually completed — i.e. the status bit did not come from B. */
        uint32_t len_b = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF) & LOG_LEN_MASK;
        if (len_b == 0u) {
            fail_at("FAIL: scenario B: LOG_CTRL[0] hwclr'd, so the transfer completed "
                    "and the latched error did not come from this region");
        }
        chk_ok("CHK-B-TRANSFER-ABORTED: LOG_CTRL[0] did not hwclr (expected nonzero)");
        info_msg_hex32_s(0, "  observed LOG_CTRL[0].LOG_LEN = ", len_b);
    }
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR, 0u,
                       "FAIL: scenario B status would not clear after abort");

    //--------------------------------------------------------------------------
    // SCENARIO C — fetch-error path with LOG_WRITE_ERR also unmasked.
    //
    // The original intent was to land the real-error term of LOG_WRITE_ERR
    // (log_write_err = 1 from an actual write DECERR).  That is NOT reachable
    // from firmware in this integration and the attempt has been removed
    // rather than left as a warning:
    //   - Reads to an unmapped fabric address DECERR cleanly (scenarios A/B/D
    //     prove this on the log_fetch master).
    //   - A WRITE to the same address via the log_write master gets no
    //     write-side error response and hangs the shared SMC fabric; the next
    //     CPU CSR access never returns and the test hits the cocotb watchdog.
    //     Reproduced on pristine replica[2].
    //   - Independently, the UART block this write master targets returns OKAY
    //     for every write offset, so no write to it can error either.
    // There is therefore deliberately NO bounded poll for BIT_WRITE_ERR here.
    // A wait that can never fire is not a check, and downgrading its expiry to
    // a warning would be worse.  The real log_write_err term stays an OPEN
    // COVERAGE GAP requiring a TB-level fabric write-error injector; it is
    // tracked as a gap and is NOT claimed by this test.
    //
    // What scenario C does claim, and does check: with LOG_WRITE_ERR also
    // unmasked, the fetch-error path still works and LOG_WRITE_ERR stays clear.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: fetch-error path with WRITE_ERR also unmasked");

    /* Same reasoning as scenario B: recover with a good fetch and prove the
     * clear holds before claiming anything about what happens next. */
    retire_fetch_err();
    assert_fetch_err_retired("FAIL: scenario C could not start from a clear LOG_FETCH_ERR");

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, GOOD_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR); /* fetch DECERRs */
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, GOOD_XFER_LEN);

    // No poll for BIT_WRITE_ERR: the fetch DECERRs first, so the write master is
    // never engaged and WRITE_ERR cannot set. Assert the fetch-error latch with
    // WRITE_ERR unmasked, and that WRITE_ERR stays clear.
    {
        uint32_t t = RELATCH_POLLS;
        while (t > 0u && (read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) {
            t--;
        }
        if (t == 0u) {
            fail_at("FAIL: scenario C: fetch DECERR did not latch with "
                    "WRITE_ERR also unmasked");
        }
        chk_ok("CHK-FETCH-DECERR-WITH-WRITE-UNMASKED: "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x1 (expected 0x1)");

        uint32_t w = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_WRITE_ERR;
        if (w != 0u) {
            fail_at("FAIL: scenario C: WRITE_ERR latched, but the fetch errors first "
                    "so no write is ever issued -- expectation is stale");
        }
        chk_ok("CHK-WRITE-ERR-STAYS-CLEAR: no write issued -> "
               "INTR_STATUS.LOG_WRITE_ERR observed 0x0 (expected 0x0)");
    }
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR | BIT_WRITE_ERR, 0u,
                       "FAIL: scenario C status would not clear after abort");

    //--------------------------------------------------------------------------
    // SCENARIO D — fetch error on replica [1], to exercise the
    // gen_uart_log_engine_wraps[1].log_engine fetch FSM specifically.
    //
    // replica[1]'s INTR_STATUS has not been touched by any scenario above, so
    // its poll reflects replica[1]'s own DECERR with no cross-replica leftover.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario D: replica[1] fetch DECERR");

#define WRAP1_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1)
#define WRAP1_UART_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1)
#define WRAP1_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(1)

    write_reg(WRAP1_CTRL_REG, 1u);
    write_reg(WRAP1_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP1_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    clear_intr_or_fail(WRAP1_LE_BASE, BIT_FETCH_ERR, BIT_FETCH_ERR,
                       "FAIL: scenario D: replica[1] did not start from a clear status");
    write_reg(WRAP1_LE_BASE + LE_REGION_SIZE_OFF, GOOD_REGION_SIZE);
    write_reg(WRAP1_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP1_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP1_LE_BASE + LE_WRITE_ADDR_OFF, WRAP1_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP1_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP1_LE_BASE + LE_LOG_CTRL0_OFF, GOOD_XFER_LEN);

    {
        uint32_t timeout = 200000u;
        while (timeout > 0u &&
               (read_reg(WRAP1_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) == 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            fail_at("FAIL: scenario D: replica[1] FETCH_ERR not detected");
        }
        chk_ok("CHK-REPLICA1-FETCH-DECERR: replica[1] "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x1 (expected 0x1)");
    }
    write_reg(WRAP1_LE_BASE + LE_CTRL_OFF, 0u);
    clear_intr_or_fail(WRAP1_LE_BASE, BIT_FETCH_ERR, 0u,
                       "FAIL: scenario D: replica[1] status would not clear");
    write_reg(WRAP1_CTRL_REG, 0u);

    // Cleanup (wrap0)
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    /* Completeness gate: every expectation above emitted exactly one CHK token.
     * Reaching this line having proven fewer of them than the test claims is a
     * failure, not a pass -- otherwise a run that fell out of any scenario
     * early would still be recorded PASS by the scratch-based verdict. */
    if (chk_count != EXPECTED_CHK_COUNT) {
        info_msg_hex32_s(0, "FAIL: incomplete run, expected CHK count=", EXPECTED_CHK_COUNT);
        info_msg_hex32_s(0, "                      observed CHK count=", chk_count);
        test_fail(0);
    }
    info_msg_hex32_s(0, "CHK-COUNT-COMPLETE: proven expectations = ", chk_count);

    info_msg_s(0, "smc_uart_log_engine_fetch_err_test done");
    test_pass(0); // noreturn

    while (1) __asm__("wfi");
    return 0;
}
