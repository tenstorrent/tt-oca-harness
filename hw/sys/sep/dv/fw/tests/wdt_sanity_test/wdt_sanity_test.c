/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Sanity Test - Watchdog Timer Functionality Test
 *
 * This test verifies watchdog timer bark and bite functionality:
 * - WDT bark interrupt triggers NMI
 * - WDT can be petted (count reset)
 * - WDT can be disabled (count stops)
 * - WDT bite triggers reset (verified via cocotb)
 *
 * Test flow:
 * 1. Set up NMI handler for WDT bark
 * 2. Initialize and enable WDT
 * 3. Wait for WDT bark interrupt (NMI)
 * 4. Pet WDT and verify count reset
 * 5. Disable WDT and verify count stops
 * 6. Re-enable WDT and let it reach BITE threshold
 * 7. Verify BITE reset fires (via cocotb)
 *
 * Note: NMI mechanism verification is done in nmi_sanity_test.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "tb.h"
#include "nmi.h"
#include "test_completion.h"
#include "aon_timer.h"

int interrupt_count;

/* Busy-wait long enough to span multiple ~200 kHz AON ticks (CPU >> AON). */
static void wait_multiple_aon_ticks(void) {
    for (volatile int i = 0; i < 200000; i++) {
        __asm__ volatile("nop");
    }
}

void wdt_nmi_handler(void) {

    interrupt_count++;

    /* Clear watchdog bark interrupt (generated field bitmask). */
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);

    if (interrupt_count == 1) {

        printf("SUCCESS: WDT bark interrupt received\n");

        ////////////////////////////////
        // STEP 4: Pet WDT and verify //
        ////////////////////////////////

        printf("\n//////////////////////////////////////////////////\n");
        printf("// STEP 4: Pet WDT and verify\n");
        printf("//////////////////////////////////////////////////\n\n");

        /* Disable watchdog to prevent re-triggering */
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

        // Read back the WDT count to verify it is non-zero (not petted yet)
        uint32_t wdt_count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (wdt_count == 0) {
            printf("ERROR: WDT count is 0! Expected non-zero\n");
            test_fail(1);
            return;
        } else {
            printf("SUCCESS: WDT count before pet: 0x%08x\n", wdt_count);
        }

        // Pet WDT
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);

        // Read back the WDT count to verify it was petted
        wdt_count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (wdt_count != 0) {
            printf("ERROR: WDT count was not petted! Expected 0, got 0x%08x\n", wdt_count);
            test_fail(1);
            return;
        } else {
            printf("SUCCESS: WDT count after pet: 0x%08x\n", wdt_count);
        }

        ////////////////////////////////////////////////
        // STEP 5: Disable WDT and verify count stops //
        ////////////////////////////////////////////////

        printf("\n//////////////////////////////////////////////////\n");
        printf("// STEP 5: Disable WDT and verify count stops\n");
        printf("//////////////////////////////////////////////////\n\n");

        /* Positive control: with enable ON, count must advance within AON window. */
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);
        wait_multiple_aon_ticks();
        wdt_count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (wdt_count == 0) {
            printf("ERROR: positive-control count did not advance (still 0)\n");
            test_fail(1);
            return;
        }
        printf("SUCCESS: positive control — count advanced to 0x%08x\n", wdt_count);

        /* Disable, confirm enable cleared, pet to 0, then prove count stays 0. */
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
        uint32_t wdog_ctrl = READ_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR);
        if ((wdog_ctrl & AON_TIMER__WDOG_CTRL__ENABLE_bm) != 0) {
            printf("ERROR: WDOG_CTRL.enable still set after disable (0x%08x)\n", wdog_ctrl);
            test_fail(1);
            return;
        }
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
        wait_multiple_aon_ticks();
        wdt_count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (wdt_count != 0) {
            printf("ERROR: WDT count advanced while disabled! got 0x%08x\n", wdt_count);
            test_fail(1);
            return;
        }
        printf("SUCCESS: WDT count stayed 0 across multi-AON window while disabled\n");

        // return to main
        return;
    } else if (interrupt_count == 2) {

        printf("SUCCESS: WDT BARK interrupt received\n");

        // Write testpass if we got to this point
        test_pass(0);

        // Loop while we wait for BITE
        while (1) {
            __asm__ volatile("wfi");
        }
    }

    /* Should never reach here */
    while (1) {
        __asm__ volatile("nop");
    }
}

int main(void) {
    /* Initialize outbound filter to allow testpass mailbox access */
    sep_outbound_filter_init();

    printf("WDT Sanity Test - Watchdog Timer Bark NMI\n");
    printf("====================================\n\n");

    // Initialize interrupt count
    interrupt_count = 0;

    ////////////////////////////////
    // STEP 1: Set up NMI handler //
    ////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 1: Set up NMI handler\n");
    printf("//////////////////////////////////////////////////\n\n");

    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    printf("SUCCESS: NMI handler set up\n");

    ////////////////////////////
    // STEP 2: Initialize WDT //
    ////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 2: Initialize WDT\n");
    printf("//////////////////////////////////////////////////\n\n");

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);

    uint32_t bark_threshold = 5000;
    uint32_t bite_threshold = 10000;

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, bite_threshold);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, bark_threshold);

    printf("Enabling watchdog...\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    printf("SUCCESS: WDT initialized\n");

    ///////////////////////////////
    // STEP 3: Wait for WDT bark //
    ///////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 3: Wait for WDT bark\n");
    printf("//////////////////////////////////////////////////\n\n");

    /* Spin forever - NMI will interrupt and exit */
    while (interrupt_count == 0) {
        __asm__ volatile("wfi");
    }

    ///////////////////////////////////////////////////////////
    // STEP 6: Re-enable WDT and let it reach BITE threshold //
    ///////////////////////////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 6: Re-enable WDT and let it reach BITE threshold\n");
    printf("//////////////////////////////////////////////////\n\n");

    // Re-enable WDT
    printf("Reenabling watchdog...\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    // Wait for BITE
    while (interrupt_count == 1) {
        __asm__ volatile("wfi");
    }

    /* Should never reach here - if we do, it's a failure */
    printf("FAIL: NMI was not triggered!\n");
    return 1;
}
