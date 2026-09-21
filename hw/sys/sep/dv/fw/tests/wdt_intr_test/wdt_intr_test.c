/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Interrupt Test (INTR_TEST injection)
 *
 * Verifies INTR_TEST register injects INTR_STATE bits and fires NMI,
 * and INTR_STATE W1C clears correctly.
 *
 * Steps:
 * 1. Set bark/bite thresholds to max (prevent accidental bark from 0>=0 condition)
 * 2. WDT disabled - write INTR_TEST bark -> NMI fires, handler clears
 * 3. Repeat injection and verify W1C
 * 4. Verify no interference with WDT counting
 *
 * Note: NMI handler kept minimal (no printf) to avoid timing issues with
 * level-triggered NMI re-entry while INTR_STATE is still being cleared.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "nmi.h"
#include "test_completion.h"
#include "aon_timer.h"

#define INTR_STATE_CLEAR_ALL \
    (AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm | AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm)

static volatile int intr_count = 0;
static volatile int intr_errors = 0;

/* Minimal NMI handler: clear INTR_STATE W1C, record count */
void wdt_nmi_handler(void) {
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);
    intr_count++;
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Interrupt Test\n");
    printf("================================\n\n");

    int errors = 0;

    /* Set thresholds to max to prevent accidental bark from 0>=0 condition */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);

    /* STEP 1: Set up NMI handler */
    printf("// STEP 1: Set up NMI handler\n");
    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();
    printf("  NMI handler registered\n");

    /* Ensure WDT is disabled and INTR_STATE is clear */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);

    /* STEP 2: First INTR_TEST injection */
    printf("\n// STEP 2: First INTR_TEST bark injection (WDT disabled)\n");
    printf("  Writing INTR_TEST = bark bitmask\n");

    int pre_count = intr_count;
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR, AON_TIMER__INTR_TEST__WDOG_TIMER_BARK_bm);

    int timeout = 2000000;
    while (intr_count == pre_count && timeout-- > 0) {
        __asm__ volatile("nop");
    }

    if (intr_count <= pre_count) {
        uint32_t st = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        printf("  FAIL: No NMI from injection 1 (count=%d, INTR_STATE=0x%08x)\n",
               intr_count - pre_count, st);
        errors++;
    } else {
        printf("  PASS: NMI fired on INTR_TEST injection\n");
    }

    /* Verify INTR_STATE cleared by handler */
    uint32_t state1 = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (state1 & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
        printf("  FAIL: INTR_STATE bark not cleared after NMI handler (0x%08x)\n", state1);
        errors++;
    } else {
        printf("  PASS: INTR_STATE clean after injection 1 (0x%08x)\n", state1);
    }

    /* STEP 3: Second injection */
    printf("\n// STEP 3: Second INTR_TEST injection\n");
    pre_count = intr_count;
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR, AON_TIMER__INTR_TEST__WDOG_TIMER_BARK_bm);

    timeout = 2000000;
    while (intr_count == pre_count && timeout-- > 0) {
        __asm__ volatile("nop");
    }

    if (intr_count <= pre_count) {
        uint32_t st = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        printf("  FAIL: No NMI from injection 2 (count=%d, INTR_STATE=0x%08x)\n",
               intr_count - pre_count, st);
        errors++;
    } else {
        printf("  PASS: Second injection fired NMI\n");
    }

    /* STEP 4: Verify INTR_STATE is clean between injections */
    printf("\n// STEP 4: Verify INTR_STATE clean between injections\n");
    uint32_t state2 = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (state2 & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
        printf("  FAIL: INTR_STATE bark still set after clear (0x%08x)\n", state2);
        errors++;
    } else {
        printf("  PASS: INTR_STATE clean (0x%08x)\n", state2);
    }

    /* Manual W1C test: INTR_TEST then poll-clear */
    printf("\n// STEP 4b: Manual INTR_STATE W1C verification\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR, AON_TIMER__INTR_TEST__WDOG_TIMER_BARK_bm);
    uint32_t st_set = 0;
    timeout = 2000000;
    while (timeout-- > 0) {
        st_set = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        if (st_set & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
            break;
        }
        __asm__ volatile("nop");
    }
    if (!(st_set & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm)) {
        printf("  FAIL: INTR_STATE bark never set after INTR_TEST (0x%08x)\n", st_set);
        errors++;
    } else {
        WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
                  AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm); /* W1C */
        uint32_t st_clr = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        if (st_clr & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
            printf("  FAIL: W1C did not clear INTR_STATE bark (set=0x%08x, clr=0x%08x)\n", st_set,
                   st_clr);
            errors++;
        } else {
            printf("  PASS: W1C cleared INTR_STATE bark (was 0x%08x)\n", st_set);
        }
    }

    /* STEP 5: Verify WDT counting not affected by INTR_TEST */
    printf("\n// STEP 5: WDT counting unaffected by INTR_TEST\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    for (volatile int i = 0; i < 30000; i++) {
        __asm__ volatile("nop");
    }
    uint32_t cnt = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDT count after spin = 0x%08x\n", cnt);
    if (cnt == 0) {
        printf("  FAIL: Counter stuck at 0 after INTR_TEST operations\n");
        errors++;
    } else {
        printf("  PASS: WDT counting normally\n");
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    errors += intr_errors;

    printf("\n================================\n");
    if (errors == 0) {
        printf("WDT Interrupt Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT Interrupt Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
