/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * AON Wakeup Timer Test
 *
 * Verifies the WKUP (wakeup) timer, which is an entirely separate 64-bit
 * counter in the same AON timer IP as the watchdog.
 *
 * Steps:
 * 1. Write WKUP_THOLD (small value), prescaler=0, enable WKUP timer
 * 2. Poll INTR_STATE wkup_timer_expired until set
 * 3. Verify WKUP_CAUSE register is set (wakeup request path)
 * 4. W1C clear INTR_STATE wkup and WKUP_CAUSE
 * 5. Verify WKUP_COUNT increments (read-back)
 * 6. Test INTR_TEST wkup injection (not tested elsewhere)
 * 7. Verify INTR_STATE wkup sets and clears via W1C after INTR_TEST injection
 *
 * Note: WKUP prescaler field is bits[12:1] of WKUP_CTRL. Prescaler=0 means
 * wkup_count increments every AON clock cycle (prescale_count resets each
 * time it equals prescaler.q). INTR_STATE wkup_timer_expired is a normal
 * (not NMI) interrupt; polling is used here.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "aon_timer.h"

#define WKUP_CTRL_PRESCALER(p) \
    ((((uint32_t)(p)) << AON_TIMER__WKUP_CTRL__PRESCALER_bp) & AON_TIMER__WKUP_CTRL__PRESCALER_bm)

#define INTR_STATE_CLEAR_ALL \
    (AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm | AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm)

/* WKUP threshold: small value for fast test (prescaler=0 → count/AON cycle) */
#define WKUP_THOLD_LO_VAL (500u)
#define WKUP_THOLD_HI_VAL (0u)

int main(void) {
    sep_outbound_filter_init();

    printf("AON Wakeup Timer Test\n");
    printf("====================================\n\n");

    int errors = 0;

    /* Clear any residual interrupts */
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR, 0x0); /* WKUP_CAUSE: W0C */

    /* STEP 1: Configure wakeup timer */
    printf("// STEP 1: Configure WKUP timer (prescaler=0, thold_lo=%u)\n", WKUP_THOLD_LO_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_THOLD_HI_BASE_ADDR, WKUP_THOLD_HI_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_THOLD_LO_BASE_ADDR, WKUP_THOLD_LO_VAL);

    /* prescaler=0 and enable */
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR,
              AON_TIMER__WKUP_CTRL__ENABLE_bm | WKUP_CTRL_PRESCALER(0));

    /* STEP 2: Poll for wkup_timer_expired */
    printf("// STEP 2: Poll INTR_STATE for wkup_timer_expired\n");
    int timeout = 5000000;
    while (timeout-- > 0) {
        uint32_t intr = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        if (intr & AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm) break;
        __asm__ volatile("nop");
    }
    if (timeout <= 0) {
        printf("  FAIL: Timeout waiting for INTR_STATE wkup_timer_expired\n");
        errors++;
    } else {
        uint32_t intr = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        printf("  PASS: INTR_STATE = 0x%08x (wkup_timer_expired set)\n", intr);
        if (intr & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
            printf("  FAIL: Unexpected INTR_STATE bark set\n");
            errors++;
        }
    }

    /* Disable wakeup timer to stop further counting */
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, 0x0);

    /* STEP 3: Verify WKUP_CAUSE is set (wakeup request path) */
    printf("\n// STEP 3: Verify WKUP_CAUSE register set\n");
    uint32_t cause = READ_REG(SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR);
    if (!(cause & AON_TIMER__WKUP_CAUSE__CAUSE_bm)) {
        printf("  FAIL: WKUP_CAUSE not set (got 0x%08x)\n", cause);
        errors++;
    } else {
        printf("  PASS: WKUP_CAUSE = 0x%08x (wakeup request set)\n", cause);
    }

    /* STEP 4: Clear INTR_STATE wkup (W1C) and WKUP_CAUSE (W0C) */
    printf("\n// STEP 4: Clear INTR_STATE wkup (W1C) and WKUP_CAUSE (W0C)\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm);    /* W1C */
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR, 0x0); /* W0C */

    /* Brief propagation delay */
    for (volatile int i = 0; i < 100; i++) {
        __asm__ volatile("nop");
    }

    uint32_t intr_after = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (intr_after & AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm) {
        printf("  FAIL: INTR_STATE wkup not cleared by W1C (0x%08x)\n", intr_after);
        errors++;
    } else {
        printf("  PASS: INTR_STATE wkup cleared\n");
    }

    uint32_t cause_after = READ_REG(SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR);
    if (cause_after & AON_TIMER__WKUP_CAUSE__CAUSE_bm) {
        printf("  FAIL: WKUP_CAUSE not cleared (0x%08x)\n", cause_after);
        errors++;
    } else {
        printf("  PASS: WKUP_CAUSE cleared\n");
    }

    /* STEP 5: Verify WKUP_COUNT increments */
    printf("\n// STEP 5: Verify WKUP_COUNT increments\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_THOLD_HI_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_THOLD_LO_BASE_ADDR, 0xFFFFFFFF);
    /* Reset count to 0 */
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_COUNT_LO_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_COUNT_HI_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR,
              AON_TIMER__WKUP_CTRL__ENABLE_bm | WKUP_CTRL_PRESCALER(0));

    for (volatile int i = 0; i < 10000; i++) {
        __asm__ volatile("nop");
    }

    uint32_t cnt_lo = READ_REG(SEP_TOP_WDT_TIMER_WKUP_COUNT_LO_BASE_ADDR);
    uint32_t cnt_hi = READ_REG(SEP_TOP_WDT_TIMER_WKUP_COUNT_HI_BASE_ADDR);
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, 0x0);

    if (cnt_lo == 0 && cnt_hi == 0) {
        printf("  FAIL: WKUP_COUNT stuck at 0 after enable\n");
        errors++;
    } else {
        printf("  PASS: WKUP_COUNT = 0x%08x_%08x (incremented)\n", cnt_hi, cnt_lo);
    }

    /* STEP 6: INTR_TEST wkup injection */
    printf("\n// STEP 6: INTR_TEST wkup injection (wkup_timer_expired)\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);

    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR,
              AON_TIMER__INTR_TEST__WKUP_TIMER_EXPIRED_bm);
    for (volatile int i = 0; i < 200; i++) {
        __asm__ volatile("nop");
    }

    uint32_t intr_injected = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (!(intr_injected & AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm)) {
        printf("  FAIL: INTR_TEST wkup did not set INTR_STATE (0x%08x)\n", intr_injected);
        errors++;
    } else {
        printf("  PASS: INTR_STATE wkup set by INTR_TEST (0x%08x)\n", intr_injected);
    }
    if (intr_injected & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
        printf("  FAIL: Unexpected INTR_STATE bark set by INTR_TEST wkup\n");
        errors++;
    }

    /* STEP 7: W1C clear after INTR_TEST injection */
    printf("\n// STEP 7: W1C clear INTR_STATE wkup after INTR_TEST\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm);
    for (volatile int i = 0; i < 100; i++) {
        __asm__ volatile("nop");
    }

    uint32_t intr_clr = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (intr_clr & AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm) {
        printf("  FAIL: W1C did not clear INTR_STATE wkup (0x%08x)\n", intr_clr);
        errors++;
    } else {
        printf("  PASS: INTR_STATE wkup cleared after W1C\n");
    }

    printf("\n====================================\n");
    if (errors == 0) {
        printf("AON Wakeup Timer Test: PASS\n");
        test_pass(0);
    } else {
        printf("AON Wakeup Timer Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("====================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
