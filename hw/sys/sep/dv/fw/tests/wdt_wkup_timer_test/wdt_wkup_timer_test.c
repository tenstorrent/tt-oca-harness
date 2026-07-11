/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * TC_WDT_013 (V2, P1) - AON Wakeup Timer Test
 *
 * Verifies the WKUP (wakeup) timer, which is an entirely separate 64-bit
 * counter in the same AON timer IP as the watchdog.
 *
 * Steps:
 * 1. Write WKUP_THOLD (small value), prescaler=0, enable WKUP timer
 * 2. Poll INTR_STATE[0] (wkup_timer_expired) until set
 * 3. Verify WKUP_CAUSE register is set (wakeup request path)
 * 4. W1C clear INTR_STATE[0] and WKUP_CAUSE
 * 5. Verify WKUP_COUNT increments (read-back)
 * 6. Test INTR_TEST[0] injection (wkup_timer_expired bit, not tested elsewhere)
 * 7. Verify INTR_STATE[0] sets and clears via W1C after INTR_TEST injection
 *
 * Note: WKUP prescaler field is bits[12:1] of WKUP_CTRL. Prescaler=0 means
 * wkup_count increments every AON clock cycle (prescale_count resets each
 * time it equals prescaler.q). INTR_STATE[0]=wkup_timer_expired is a normal
 * (not NMI) interrupt; polling is used here.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/* WKUP_CTRL bits: enable=bit[0], prescaler=bits[12:1] */
#define WKUP_CTRL_ENABLE (0x1u)
#define WKUP_CTRL_PRESCALER(p) (((p)&0xFFFu) << 1)

/* INTR_STATE bit[0] = wkup_timer_expired */
#define INTR_STATE_WKUP_BIT (0x1u)
/* INTR_STATE bit[1] = wdog_timer_bark */
#define INTR_STATE_WDOG_BIT (0x2u)

/* WKUP threshold: small value for fast test (prescaler=0 → count/AON cycle) */
#define WKUP_THOLD_LO_VAL (500u)
#define WKUP_THOLD_HI_VAL (0u)

int main(void) {
    sep_outbound_filter_init();

    printf("TC_WDT_013: AON Wakeup Timer Test\n");
    printf("====================================\n\n");

    int errors = 0;

    /* Clear any residual interrupts */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3); /* INTR_STATE: W1C */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR, 0x0); /* WKUP_CAUSE: W0C */

    /* STEP 1: Configure wakeup timer */
    printf("// STEP 1: Configure WKUP timer (prescaler=0, thold_lo=%u)\n", WKUP_THOLD_LO_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_THOLD_HI_BASE_ADDR, WKUP_THOLD_HI_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_THOLD_LO_BASE_ADDR, WKUP_THOLD_LO_VAL);

    /* prescaler=0 and enable */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, WKUP_CTRL_ENABLE | WKUP_CTRL_PRESCALER(0));

    /* STEP 2: Poll for wkup_timer_expired (INTR_STATE[0]) */
    printf("// STEP 2: Poll INTR_STATE[0] for wkup_timer_expired\n");
    int timeout = 5000000;
    while (timeout-- > 0) {
        uint32_t intr = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        if (intr & INTR_STATE_WKUP_BIT) break;
        __asm__ volatile("nop");
    }
    if (timeout <= 0) {
        printf("  FAIL: Timeout waiting for INTR_STATE[0] (wkup_timer_expired)\n");
        errors++;
    } else {
        uint32_t intr = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        printf("  PASS: INTR_STATE = 0x%08x (wkup_timer_expired set)\n", intr);
        if (intr & INTR_STATE_WDOG_BIT) {
            printf("  FAIL: Unexpected INTR_STATE[1] (wdog_bark) set\n");
            errors++;
        }
    }

    /* Disable wakeup timer to stop further counting */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, 0x0);

    /* STEP 3: Verify WKUP_CAUSE is set (wakeup request path) */
    printf("\n// STEP 3: Verify WKUP_CAUSE register set\n");
    uint32_t cause = READ_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR);
    if (!(cause & 0x1)) {
        printf("  FAIL: WKUP_CAUSE[0] not set (got 0x%08x)\n", cause);
        errors++;
    } else {
        printf("  PASS: WKUP_CAUSE = 0x%08x (wakeup request set)\n", cause);
    }

    /* STEP 4: Clear INTR_STATE[0] (W1C) and WKUP_CAUSE (W0C) */
    printf("\n// STEP 4: Clear INTR_STATE[0] (W1C) and WKUP_CAUSE (W0C)\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_WKUP_BIT); /* W1C */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR, 0x0);                 /* W0C */

    /* Brief propagation delay */
    for (volatile int i = 0; i < 100; i++) {
        __asm__ volatile("nop");
    }

    uint32_t intr_after = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (intr_after & INTR_STATE_WKUP_BIT) {
        printf("  FAIL: INTR_STATE[0] not cleared by W1C (0x%08x)\n", intr_after);
        errors++;
    } else {
        printf("  PASS: INTR_STATE[0] cleared\n");
    }

    uint32_t cause_after = READ_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CAUSE_BASE_ADDR);
    if (cause_after & 0x1) {
        printf("  FAIL: WKUP_CAUSE not cleared (0x%08x)\n", cause_after);
        errors++;
    } else {
        printf("  PASS: WKUP_CAUSE cleared\n");
    }

    /* STEP 5: Verify WKUP_COUNT increments */
    printf("\n// STEP 5: Verify WKUP_COUNT increments\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_THOLD_HI_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_THOLD_LO_BASE_ADDR, 0xFFFFFFFF);
    /* Reset count to 0 */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_COUNT_LO_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_COUNT_HI_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, WKUP_CTRL_ENABLE | WKUP_CTRL_PRESCALER(0));

    for (volatile int i = 0; i < 10000; i++) {
        __asm__ volatile("nop");
    }

    uint32_t cnt_lo = READ_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_COUNT_LO_BASE_ADDR);
    uint32_t cnt_hi = READ_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_COUNT_HI_BASE_ADDR);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, 0x0);

    if (cnt_lo == 0 && cnt_hi == 0) {
        printf("  FAIL: WKUP_COUNT stuck at 0 after enable\n");
        errors++;
    } else {
        printf("  PASS: WKUP_COUNT = 0x%08x_%08x (incremented)\n", cnt_hi, cnt_lo);
    }

    /* STEP 6: INTR_TEST[0] injection (wkup_timer_expired) */
    printf("\n// STEP 6: INTR_TEST[0] injection (wkup_timer_expired)\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3); /* clear residual */

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR, INTR_STATE_WKUP_BIT); /* inject wkup */
    for (volatile int i = 0; i < 200; i++) {
        __asm__ volatile("nop");
    }

    uint32_t intr_injected = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (!(intr_injected & INTR_STATE_WKUP_BIT)) {
        printf("  FAIL: INTR_TEST[0] did not set INTR_STATE[0] (0x%08x)\n", intr_injected);
        errors++;
    } else {
        printf("  PASS: INTR_STATE[0] set by INTR_TEST[0] injection (0x%08x)\n", intr_injected);
    }
    if (intr_injected & INTR_STATE_WDOG_BIT) {
        printf("  FAIL: Unexpected INTR_STATE[1] set by INTR_TEST[0]\n");
        errors++;
    }

    /* STEP 7: W1C clear after INTR_TEST injection */
    printf("\n// STEP 7: W1C clear INTR_STATE[0] after INTR_TEST\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_WKUP_BIT);
    for (volatile int i = 0; i < 100; i++) {
        __asm__ volatile("nop");
    }

    uint32_t intr_clr = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (intr_clr & INTR_STATE_WKUP_BIT) {
        printf("  FAIL: W1C did not clear INTR_STATE[0] (0x%08x)\n", intr_clr);
        errors++;
    } else {
        printf("  PASS: INTR_STATE[0] cleared after W1C\n");
    }

    printf("\n====================================\n");
    if (errors == 0) {
        printf("TC_WDT_013: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_013: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("====================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
