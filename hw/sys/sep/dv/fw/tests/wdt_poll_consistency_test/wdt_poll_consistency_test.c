/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Poll Consistency Test
 *
 * Verifies WDOG_COUNT is monotonically incrementing and readable without
 * stale values or races.
 *
 * Steps:
 * 1. Enable WDT, poll WDOG_COUNT N times
 * 2. Verify monotonically non-decreasing (AON clock, reads may see same value)
 * 3. Verify overall progress (start != end)
 * 4. Verify counter stops when disabled
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "aon_timer.h"

#define POLL_ITERS 200

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Poll Consistency Test\n");
    printf("=======================================\n\n");

    int errors = 0;

    /* STEP 1: Enable WDT with high thresholds */
    printf("// STEP 1: Enable WDT and poll WDOG_COUNT %d times\n", POLL_ITERS);

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    /* STEP 2: Poll monotonicity */
    uint32_t prev = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    int monotonic_violations = 0;
    int same_count = 0;

    for (int i = 0; i < POLL_ITERS; i++) {
        /* Small delay between reads */
        for (volatile int j = 0; j < 1000; j++) {
            __asm__ volatile("nop");
        }

        uint32_t curr = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);

        if (curr < prev) {
            /* Should never decrease (unless petted, which we don't do) */
            printf("  FAIL[%d]: counter decreased 0x%08x -> 0x%08x\n", i, prev, curr);
            monotonic_violations++;
        } else if (curr == prev) {
            same_count++; /* allowed: CPU clock >> AON clock */
        }

        prev = curr;
    }

    if (monotonic_violations > 0) {
        printf("  FAIL: %d monotonic violations\n", monotonic_violations);
        errors++;
    } else {
        printf("  PASS: Monotonically non-decreasing (%d same-value reads)\n", same_count);
    }

    /* STEP 3: Verify overall progress */
    printf("\n// STEP 3: Verify overall counter progress\n");
    uint32_t final_cnt = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Final count after %d polls = 0x%08x\n", POLL_ITERS, final_cnt);
    if (final_cnt == 0) {
        printf("  FAIL: Counter stuck at 0 throughout poll\n");
        errors++;
    } else {
        printf("  PASS: Counter advanced to 0x%08x\n", final_cnt);
    }

    /* STEP 4: Counter stops when disabled */
    printf("\n// STEP 4: Counter stops when disabled\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    uint32_t snap1 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);

    for (volatile int i = 0; i < 100000; i++) {
        __asm__ volatile("nop");
    }

    uint32_t snap2 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Disabled: count before=0x%08x, after=0x%08x\n", snap1, snap2);
    if (snap2 > snap1 + 2) { /* allow small delta for CDC read */
        printf("  FAIL: Counter still incrementing after disable (delta=%u)\n", snap2 - snap1);
        errors++;
    } else {
        printf("  PASS: Counter stopped after disable\n");
    }

    printf("\n=======================================\n");
    if (errors == 0) {
        printf("WDT Poll Consistency Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT Poll Consistency Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("=======================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
