/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Fetch Error
 *
 * Verifies that a bus error on the log engine fetch path sets the fetch error
 * status bit on both UART log engine wrappers, that the bit latches the error
 * as an event, so a clear holds once the engine is stopped, and that the engine
 * then runs a good transfer. A fetch error comes from pointing the engine at an
 * unmapped fabric address, and an entry aborted by one must not complete. The
 * status latches whether or not its interrupt is enabled. A write error cannot
 * be raised from firmware in this integration, so the write error bit is set
 * only through the interrupt-test register and is otherwise checked to stay
 * clear.
 *
 * Before each injected error the status is proven clear, and after an earlier
 * error also proven to stay clear, so each wait can only be satisfied by the
 * new error. The test fails unless every check ran.
 */

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

#define BIT_FETCH_ERR (1u << 0)
#define BIT_WRITE_ERR (1u << 4)
#define LOG_LEN_MASK 0xFFFFu

/* First 4 KB-aligned address past the WDT cluster: unmapped, so a fetch there
 * gets a decode error from the fabric. */
#define WDT_REGION_END \
    (SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR + SMC_TOP_SMC_CLUSTER_CORE3_WDT_SIZE)
#define UNMAPPED_ADDR (((WDT_REGION_END) + 0xFFFu) & ~0xFFFu)
#define UNMAPPED_SPAN 0x1000u /* largest region any scenario below programs */

/* The whole span must lie in the gap before the reset unit, so a map change
 * that closes the gap fails the build instead of aiming the engine at a real
 * slave. */
_Static_assert(UNMAPPED_ADDR >= WDT_REGION_END,
               "UNMAPPED_ADDR must start at or after the end of the WDT region");
_Static_assert(UNMAPPED_ADDR + UNMAPPED_SPAN <= SMC_TOP_SMC_RESET_UNIT_BASE_ADDR,
               "UNMAPPED_ADDR + span must end at or before the reset unit base");

/* Mapped SPM source for the good transfers that show the engine recovers. */
#define LOG_BUF_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)
#define GOOD_REGION_SIZE 0x100u /* 16-byte slots */
#define GOOD_XFER_LEN 16u       /* fits the UART FIFOs, so loopback cannot overrun */

/* Samples taken to show that a status bit stays clear or to wait for a latch.
 * Each sample is a register read across the fabric, so the window spans many
 * engine clocks; the bound makes a missing latch fail instead of hang. */
#define RELATCH_POLLS 2000u

static void fail_at(const char *msg) {
    info_msg_s(0, msg);
    test_fail(0);
}

/* Every passing check prints one CHK line and is counted. main() fails unless
 * the count equals EXPECTED_CHK_COUNT, so a run that skips a check cannot pass.
 * Keep EXPECTED_CHK_COUNT equal to the number of chk_ok() calls a full run
 * makes. */
#define EXPECTED_CHK_COUNT 16u
static uint32_t chk_count;

static void chk_ok(const char *line) {
    info_msg_s(0, line);
    chk_count++;
}

/* Clear the given status bits, fail if any stays set, then set the interrupt
 * enable. Valid only once the cause has stopped: a running engine on an
 * unmapped region keeps raising fetch errors, and the enable does not mask the
 * status. */
static void clear_intr_or_fail(uint64_t le_base, uint32_t bits, uint32_t restore_enable,
                               const char *where) {
    write_reg(le_base + LE_INTR_STATUS_OFF, bits);
    uint32_t left = read_reg(le_base + LE_INTR_STATUS_OFF) & bits;
    if (left != 0u) {
        info_msg_hex32_s(0, "FAIL: W1C left status bits set, mask=", left);
        fail_at(where);
    }
    write_reg(le_base + LE_INTR_ENABLE_OFF, restore_enable);
}

/* UART at the fastest rate with 8-bit words, FIFOs and internal loopback, so
 * the engine's writes drain and a good transfer can complete. */
static void setup_uart_for_log_writes(void) {
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u);
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u);
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u);
}

/* Show that the engine recovers after an aborted fetch: a 16-byte transfer
 * from SPM must complete, which hardware reports by clearing the entry length.
 * Expiry of the bound fails the test. */
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

/* Clear the fetch error status and require it to stay clear over the settle
 * window, so the next scenario's poll can only be satisfied by its own error. */
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

    // The fetch error status must start clear
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);

    if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR) != 0u) {
        fail_at("FAIL: status did not clear at start");
    }

    //--------------------------------------------------------------------------
    // SCENARIO 0: each test pulse sets the matching status bits, which then
    // clear. It runs before any real error because a test pulse is the only
    // error cause firmware can raise and retire on demand.
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
            /* A test pulse lasts one cycle, so the clear must hold. */
            clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR | BIT_WRITE_ERR,
                               BIT_FETCH_ERR | BIT_WRITE_ERR,
                               "FAIL: scenario 0 status would not clear after INTR_TEST pulse");
        }
    }

    //--------------------------------------------------------------------------
    // SCENARIO 0b: the enable masks the interrupt output, not the status. The
    // enabled arm shows that a pulse sets the bit now, so the masked arm's
    // latch cannot come from a dead source or a stale bit.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario 0b: INTR_ENABLE masks the output, not INTR_STATUS capture");
    { /* enabled: a test pulse sets the bit */
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
    { /* masked: the same pulse also sets the bit, and it clears while masked */
        clear_intr_or_fail(WRAP0_LE_BASE, BIT_FETCH_ERR, 0u,
                           "FAIL: could not clear before the ENABLE=0 capture arm");
        write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, BIT_FETCH_ERR);
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
        if (s != BIT_FETCH_ERR) {
            info_msg_hex32_s(0, "FAIL: ENABLE=0 INTR_TEST pulse was lost, status=", s);
            fail_at("FAIL: INTR_STATUS must capture while masked (INTR_ENABLE masks "
                    "irq_o only)");
        }
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
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
    // SCENARIO A: a fetch from a 256-byte unmapped region sets the fetch error
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

    /* With the engine stopped no further error can arrive, so the clear must
     * hold: the status latched an event rather than following a level. */
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    {
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR);
        for (uint32_t i = 0; i < RELATCH_POLLS; i++) {
            uint32_t r = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & BIT_FETCH_ERR;
            if (r != 0u) {
                info_msg_hex32_s(0,
                                 "FAIL: LOG_FETCH_ERR re-latched with the engine stopped, "
                                 "status=",
                                 r);
                fail_at("FAIL: log_fetch_err is behaving as a level, not an event");
            }
        }
        chk_ok("CHK-FETCH-ERR-IS-EVENT: engine stopped, W1C -> "
               "INTR_STATUS.LOG_FETCH_ERR observed 0x0 on every sample (expected 0x0)");
    }

    //--------------------------------------------------------------------------
    // SCENARIO B: a long entry over a 4 KB unmapped region raises the fetch
    // error and does not complete. A good transfer runs first and the status
    // is shown to stay clear, so the poll can only be satisfied by this
    // scenario's error.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: sustained DECERR fetch on large region");

    retire_fetch_err();
    assert_fetch_err_retired("FAIL: scenario B could not start from a clear LOG_FETCH_ERR");

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, UNMAPPED_SPAN);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    /* Long enough that the engine issues many fetch attempts. */
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
        /* The aborted transfer must leave its length set; a cleared length
         * would mean the transfer completed and the error came from elsewhere. */
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
    // SCENARIO C: with the write error interrupt also enabled, a fetch error
    // still latches and the write error stays clear. A write error cannot be
    // raised from firmware in this integration, so the scenario does not wait
    // for one.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: fetch-error path with WRITE_ERR also unmasked");

    /* Recover and show that the clear holds, as in scenario B. */
    retire_fetch_err();
    assert_fetch_err_retired("FAIL: scenario C could not start from a clear LOG_FETCH_ERR");

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, GOOD_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, UNMAPPED_ADDR);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, GOOD_XFER_LEN);

    // The fetch fails first, so the engine never writes and the write error
    // cannot set.
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
    // SCENARIO D: a fetch from an unmapped region on wrapper 1 sets that
    // wrapper's fetch error. No earlier scenario touches wrapper 1, so the
    // latch is its own.
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

    // Cleanup
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    // Every check above must have run
    if (chk_count != EXPECTED_CHK_COUNT) {
        info_msg_hex32_s(0, "FAIL: incomplete run, expected CHK count=", EXPECTED_CHK_COUNT);
        info_msg_hex32_s(0, "                      observed CHK count=", chk_count);
        test_fail(0);
    }
    info_msg_hex32_s(0, "CHK-COUNT-COMPLETE: proven expectations = ", chk_count);

    info_msg_s(0, "smc_uart_log_engine_fetch_err_test done");
    test_pass(0);
}
