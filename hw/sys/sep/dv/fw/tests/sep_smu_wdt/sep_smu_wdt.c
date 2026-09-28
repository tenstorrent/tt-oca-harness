/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_wdt - SMU-level SEP WDT register sanity test.
 *
 * Programs the SEP watchdog timer's control, threshold, count and
 * interrupt-state registers over the SEP-to-WDT CSR path, then reads every one
 * of them back and returns a distinct non-zero code for the first programmed
 * value that did not stick. Bark and bite flows stay disabled -- WDOG_CTRL and
 * WKUP_CTRL are both programmed with their enable clear, so neither counter
 * runs -- which keeps the image deterministic while making the readbacks the
 * whole on-chip check.
 *
 * Every programmed register is written away from its reset value, so each
 * readback is a reset-to-programmed delta that a block which took no write,
 * or unmapped space reading as zero, cannot satisfy: the control registers
 * carry a non-reset bit that keeps the counter stopped (WDOG_CTRL.PAUSE_IN_SLEEP
 * with ENABLE clear; a non-zero WKUP_CTRL.PRESCALER with ENABLE clear), the
 * count is preloaded, and all three thresholds are non-zero. INTR_STATE is
 * write-one-to-clear, so its contract is that both defined bits read clear
 * after the clear-all write, not that the written word reads back.
 *
 * Register addresses come from the generated SEP address map by symbol
 * (SEP_TOP_WDT_TIMER_*, hw/sys/sep/regs/gen/c/sep_addr.h via sep.h) -- this
 * is the SEP's own WDT, not the SMC's -- and the field masks from the generated
 * block header by symbol (AON_TIMER__*_bm, aon_timer.h).
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "aon_timer.h"

static volatile int g_wdt_status;

/* Programmed values, shared by each write and its own readback so the check has
 * one source. Both ENABLE bits stay clear so neither counter runs. */
#define WDT_WDOG_CTRL_PROG AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm
#define WDT_WDOG_COUNT_PROG 0x30u
#define WDT_WDOG_BARK_THOLD_PROG 0x200u
#define WDT_WDOG_BITE_THOLD_PROG 0x400u
#define WDT_WKUP_CTRL_PROG (0x5u << AON_TIMER__WKUP_CTRL__PRESCALER_bp)
#define WDT_WKUP_THOLD_LO_PROG 0x100u
#define WDT_WKUP_THOLD_HI_PROG 0x3u

/* Clears every interrupt-state bit the block implements and any it does not. */
#define WDT_INTR_STATE_CLEAR_ALL 0xFFFFFFFFu
#define WDT_INTR_STATE_EXPECTED 0x0u

/* Each readback is compared only over the bits its register implements. */
#define WDT_WDOG_CTRL_MASK \
    (AON_TIMER__WDOG_CTRL__ENABLE_bm | AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm)
#define WDT_WDOG_COUNT_MASK AON_TIMER__WDOG_COUNT__COUNT_bm
#define WDT_WDOG_BARK_THOLD_MASK AON_TIMER__WDOG_BARK_THOLD__THRESHOLD_bm
#define WDT_WDOG_BITE_THOLD_MASK AON_TIMER__WDOG_BITE_THOLD__THRESHOLD_bm
#define WDT_WKUP_CTRL_MASK (AON_TIMER__WKUP_CTRL__ENABLE_bm | AON_TIMER__WKUP_CTRL__PRESCALER_bm)
#define WDT_WKUP_THOLD_LO_MASK AON_TIMER__WKUP_THOLD_LO__THRESHOLD_LO_bm
#define WDT_WKUP_THOLD_HI_MASK AON_TIMER__WKUP_THOLD_HI__THRESHOLD_HI_bm
#define WDT_INTR_STATE_MASK \
    (AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm | AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm)

static inline void fence_io(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline int wdt_readback_holds(uintptr_t addr, uint32_t mask, uint32_t expected) {
    return (READ_REG(addr) & mask) == (expected & mask);
}

static int run_wdt_programming_sequence(void) {
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDT_WDOG_CTRL_PROG);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, WDT_WDOG_COUNT_PROG);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, WDT_WDOG_BARK_THOLD_PROG);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, WDT_WDOG_BITE_THOLD_PROG);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, WDT_INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, WDT_WKUP_CTRL_PROG);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_THOLD_LO_BASE_ADDR, WDT_WKUP_THOLD_LO_PROG);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_THOLD_HI_BASE_ADDR, WDT_WKUP_THOLD_HI_PROG);

    /* All eight stores retire before the first readback is issued. */
    fence_io();

    /* Thresholds first: the widest deltas. */
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, WDT_WDOG_BARK_THOLD_MASK,
                            WDT_WDOG_BARK_THOLD_PROG)) {
        return -1;
    }
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, WDT_WDOG_BITE_THOLD_MASK,
                            WDT_WDOG_BITE_THOLD_PROG)) {
        return -2;
    }
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WKUP_THOLD_LO_BASE_ADDR, WDT_WKUP_THOLD_LO_MASK,
                            WDT_WKUP_THOLD_LO_PROG)) {
        return -3;
    }

    /* Control, count and the high threshold: non-reset values with the
     * counters still stopped. */
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDT_WDOG_CTRL_MASK,
                            WDT_WDOG_CTRL_PROG)) {
        return -4;
    }
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, WDT_WDOG_COUNT_MASK,
                            WDT_WDOG_COUNT_PROG)) {
        return -5;
    }
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, WDT_WKUP_CTRL_MASK,
                            WDT_WKUP_CTRL_PROG)) {
        return -6;
    }
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_WKUP_THOLD_HI_BASE_ADDR, WDT_WKUP_THOLD_HI_MASK,
                            WDT_WKUP_THOLD_HI_PROG)) {
        return -7;
    }

    /* Write-one-to-clear: both defined bits must read clear after the write. */
    if (!wdt_readback_holds(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, WDT_INTR_STATE_MASK,
                            WDT_INTR_STATE_EXPECTED)) {
        return -8;
    }

    return 0;
}

__attribute__((used, noinline, noreturn)) void smu_sep_wdt_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

/* The extra nop keeps this body distinct from the pass loop, so the two park
 * at addresses the testbench can tell apart. */
__attribute__((used, noinline, noreturn)) void smu_sep_wdt_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
        __asm__ volatile("nop");
    }
}

int main(void) {
    sep_outbound_filter_init();
    g_wdt_status = run_wdt_programming_sequence();
    if (g_wdt_status == 0) {
        smu_sep_wdt_pass_loop();
    } else {
        smu_sep_wdt_fail_loop();
    }
}
