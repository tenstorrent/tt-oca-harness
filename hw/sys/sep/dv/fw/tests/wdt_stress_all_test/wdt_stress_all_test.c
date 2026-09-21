/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Stress All Test
 *
 * Comprehensive stress: enable/disable cycles, threshold changes, pets,
 * interrupt injections, and combined operations.
 *
 * Steps:
 * 1. 5x enable/disable cycles with pets
 * 2. Alternating threshold changes (high→low→high)
 * 3. 3x interrupt injections via INTR_TEST + NMI handler
 * 4. Combined: enable, change threshold, pet, bark, pet, disable
 * 5. Verify no register corruption throughout
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

static volatile int nmi_count = 0;
static volatile int nmi_errors = 0;

void wdt_nmi_handler(void) {
    nmi_count++;
    uint32_t state = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);
    if (!(state & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm)) {
        nmi_errors++;
        printf("  ERROR: NMI fired but INTR_STATE bark=0 (state=0x%08x)\n", state);
    }
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Stress All Test\n");
    printf("================================\n\n");

    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    int errors = 0;

    /* STEP 1: 5x enable/disable cycles */
    printf("// STEP 1: 5x enable/disable cycles with pet\n");
    for (int i = 0; i < 5; i++) {
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

        for (volatile int j = 0; j < 10000; j++) {
            __asm__ volatile("nop");
        }

        uint32_t cnt = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0); /* pet */
        uint32_t after = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);

        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0); /* disable */

        printf("  Cycle %d: count=%u, after_pet=%u\n", i + 1, cnt, after);
        if (after > 0x200) {
            printf("  FAIL: Pet did not reset count in cycle %d\n", i + 1);
            errors++;
        }
    }

    /* STEP 2: Alternating thresholds */
    printf("\n// STEP 2: Alternating threshold changes\n");
    uint32_t tholds[] = {0xFFFFFFFF, 0x1000, 0xFFFFFFFF, 0x5000, 0xFFFFFFFF};
    for (int i = 0; i < 5; i++) {
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, tholds[i]);
        uint32_t rd = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
        if (rd != tholds[i]) {
            printf("  FAIL: BARK_THOLD[%d] expected 0x%08x got 0x%08x\n", i, tholds[i], rd);
            errors++;
        } else {
            printf("  PASS: BARK_THOLD[%d] = 0x%08x\n", i, rd);
        }
    }

    /* STEP 3: 3x INTR_TEST injections */
    printf("\n// STEP 3: 3x INTR_TEST injections\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    for (int i = 0; i < 3; i++) {
        int prev = nmi_count;
        WRITE_REG(SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR,
                  AON_TIMER__INTR_TEST__WDOG_TIMER_BARK_bm);
        int timeout = 2000000;
        while (nmi_count == prev && timeout-- > 0) {
            __asm__ volatile("nop");
        }
        if (nmi_count <= prev) {
            uint32_t st = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
            printf("  FAIL: INTR_TEST injection %d NMI not received (INTR_STATE=0x%08x)\n", i + 1,
                   st);
            errors++;
        } else {
            printf("  PASS: INTR_TEST injection %d NMI received\n", i + 1);
        }
    }

    /* STEP 4: Combined operation */
    printf("\n// STEP 4: Combined - enable, change threshold, bark, pet, disable\n");
    int bark_pre = nmi_count;
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);
    /* Let count reach ~200 then change bark to trigger */
    while (READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR) < 200) {
        __asm__ volatile("nop");
    }
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 50); /* below current count */

    /* Wait for NMI */
    for (volatile int i = 0; i < 2000000 && nmi_count == bark_pre; i++) {
        __asm__ volatile("nop");
    }
    if (nmi_count == bark_pre) {
        printf("  FAIL: Bark NMI not fired after threshold jump\n");
        errors++;
    } else {
        printf("  PASS: Bark fired after threshold change\n");
    }

    /* Pet and verify no further bark immediately */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    int after_pet_nmi = nmi_count;
    for (volatile int i = 0; i < 100000; i++) {
        __asm__ volatile("nop");
    }
    if (nmi_count != after_pet_nmi) {
        printf("  FAIL: NMI fired after pet + high threshold\n");
        errors++;
    } else {
        printf("  PASS: No spurious NMI after pet + high threshold\n");
    }
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 5: Verify register values not corrupted */
    printf("\n// STEP 5: Final register consistency check\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xDEAD1234);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xBEEF5678);
    uint32_t bk = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
    uint32_t bt = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR);
    if (bk != 0xDEAD1234 || bt != 0xBEEF5678) {
        printf("  FAIL: Register corruption (bark=0x%08x, bite=0x%08x)\n", bk, bt);
        errors++;
    } else {
        printf("  PASS: No register corruption\n");
    }

    errors += nmi_errors;

    printf("\n================================\n");
    if (errors == 0) {
        printf("WDT Stress All Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT Stress All Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
