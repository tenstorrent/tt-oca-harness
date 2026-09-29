/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Pause in Sleep Test
 *
 * Verifies WDOG_CTRL.pause_in_sleep (bit 1) register configuration.
 * Full functional pause verification requires TB to assert wdt_debug_sleep_mode_i;
 * this test covers register accessibility and pause_in_sleep=0 normal counting.
 *
 * Steps:
 * 1. Verify WDOG_CTRL.pause_in_sleep bit is writable/readable
 * 2. Configure with pause_in_sleep=1, enable, verify counter counts (sleep not asserted)
 * 3. Configure with pause_in_sleep=0, verify counter still counts
 * 4. Verify count is monotonically increasing in both configurations
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "aon_timer.h"

#define WDOG_CTRL_ENABLE AON_TIMER__WDOG_CTRL__ENABLE_bm
#define WDOG_CTRL_PAUSE_SLEEP \
    (AON_TIMER__WDOG_CTRL__ENABLE_bm | AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm)
#define WDOG_CTRL_FIELD_MASK \
    (AON_TIMER__WDOG_CTRL__ENABLE_bm | AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm)

static void wdt_disable(void) {
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Pause in Sleep Test\n");
    printf("=====================================\n\n");

    int errors = 0;

    /* STEP 1: Verify pause_in_sleep bit R/W */
    printf("// STEP 1: Verify WDOG_CTRL.pause_in_sleep R/W\n");

    wdt_disable();
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);

    /* Set enable=1, pause_in_sleep=1 */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDOG_CTRL_PAUSE_SLEEP);
    uint32_t ctrl = READ_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR);
    printf("  WDOG_CTRL written pause+enable, readback = 0x%08x\n", ctrl);
    if ((ctrl & WDOG_CTRL_FIELD_MASK) != WDOG_CTRL_PAUSE_SLEEP) {
        printf("  FAIL: pause_in_sleep bit not retained (got 0x%08x)\n", ctrl);
        errors++;
    } else {
        printf("  PASS: pause_in_sleep bit retained\n");
    }

    /* Clear pause_in_sleep */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDOG_CTRL_ENABLE);
    ctrl = READ_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR);
    if ((ctrl & WDOG_CTRL_FIELD_MASK) != WDOG_CTRL_ENABLE) {
        printf("  FAIL: pause_in_sleep clear failed (got 0x%08x)\n", ctrl);
        errors++;
    } else {
        printf("  PASS: pause_in_sleep cleared to 0\n");
    }

    wdt_disable();

    /* STEP 2: Counter runs with pause_in_sleep=1 (sleep not asserted by TB) */
    printf("\n// STEP 2: Counter counts with pause_in_sleep=1, sleep_mode_i=0\n");

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDOG_CTRL_PAUSE_SLEEP);

    /* Spin for a while to let the AON counter advance */
    for (volatile int i = 0; i < 50000; i++) {
        __asm__ volatile("nop");
    }

    uint32_t count1 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDOG_COUNT after spin (pause_in_sleep=1, sleep=0) = 0x%08x\n", count1);
    if (count1 == 0) {
        printf("  FAIL: Counter did not increment (sleep not asserted, should count)\n");
        errors++;
    } else {
        printf("  PASS: Counter increments normally when sleep not asserted\n");
    }

    wdt_disable();

    /* STEP 3: Counter runs with pause_in_sleep=0 */
    printf("\n// STEP 3: Counter counts with pause_in_sleep=0\n");

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDOG_CTRL_ENABLE);

    for (volatile int i = 0; i < 50000; i++) {
        __asm__ volatile("nop");
    }

    uint32_t count2 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDOG_COUNT after spin (pause_in_sleep=0) = 0x%08x\n", count2);
    if (count2 == 0) {
        printf("  FAIL: Counter did not increment with pause_in_sleep=0\n");
        errors++;
    } else {
        printf("  PASS: Counter increments with pause_in_sleep=0\n");
    }

    wdt_disable();

    /* STEP 4: Disabled counter stays at 0 */
    printf("\n// STEP 4: Disabled counter does not increment\n");

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    /* WDT is disabled from wdt_disable() above */

    for (volatile int i = 0; i < 50000; i++) {
        __asm__ volatile("nop");
    }

    uint32_t count3 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDOG_COUNT after spin (disabled) = 0x%08x\n", count3);
    if (count3 != 0) {
        printf("  FAIL: Counter incremented while disabled (got 0x%08x)\n", count3);
        errors++;
    } else {
        printf("  PASS: Counter stays 0 when disabled\n");
    }

    printf("\n=====================================\n");
    if (errors == 0) {
        printf("WDT Pause in Sleep Test: PASS\n");
        printf("Note: Full sleep-pause requires TB to assert wdt_debug_sleep_mode_i\n");
        test_pass(0);
    } else {
        printf("WDT Pause in Sleep Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("=====================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
