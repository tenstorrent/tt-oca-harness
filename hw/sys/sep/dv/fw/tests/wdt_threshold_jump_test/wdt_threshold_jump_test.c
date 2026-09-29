/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Threshold Jump Test
 *
 * Tests that lowering a watchdog threshold below the current count triggers
 * the event immediately (same-cycle response).
 *
 * Test flow:
 * 1. Initialize NMI handler
 * 2. BARK test: count=50, bark=1000 -> start -> bark=20 -> verify interrupt
 * 3. BITE test: count=100, bite=1000 -> start -> bite=20 -> verify reset (cocotb)
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

void wdt_nmi_handler(void) {

    interrupt_count++;

    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);

    printf("SUCCESS: WDT bark interrupt received\n");
}

int main(void) {
    /* Initialize outbound filter to allow testpass mailbox access */
    sep_outbound_filter_init();

    printf("WDT Threshold Jump Test\n");
    printf("========================\n\n");

    /* Initialize interrupt count */
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

    ////////////////////////////////////////////////
    // STEP 2: BARK threshold jump test           //
    // count=50, bark=1000 -> bark=20 -> interrupt //
    ////////////////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 2: BARK threshold jump test\n");
    printf("//////////////////////////////////////////////////\n\n");

    /* Set initial values with high thresholds */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 50);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 1000);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);

    printf("Set count=50, bark=1000, bite=0xFFFFFFFF\n");

    /* Enable WDT */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);
    printf("WDT enabled\n");

    /* Confirm no bark yet with unreachable threshold (count=50 < bark=1000). */
    uint32_t intr_before = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (intr_before & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
        printf("ERROR: BARK already set before threshold jump (INTR_STATE=0x%08x)\n", intr_before);
        test_fail(1);
        return 1;
    }

    /* Lower bark threshold below current count to trigger interrupt. */
    printf("Lowering bark threshold to 20...\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 20);

    /* Wait for NMI */
    while (interrupt_count == 0) {
        __asm__ volatile("wfi");
    }

    /* Correlate: bark thold is the jumped value and count is past it. */
    uint32_t bark_thold = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
    uint32_t count_at_bark = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    if (bark_thold != 20) {
        printf("ERROR: bark thold not jumped (got %u)\n", bark_thold);
        test_fail(1);
        return 1;
    }
    if (count_at_bark < 20) {
        printf("ERROR: count 0x%08x < jumped bark thold 20\n", count_at_bark);
        test_fail(1);
        return 1;
    }
    printf("CHK-BARK-JUMP: thold=%u count=0x%08x\n", bark_thold, count_at_bark);

    /* Disable WDT */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    printf("WDT disabled\n");

    /* Verify interrupt fired */
    if (interrupt_count != 1) {
        printf("ERROR: Expected 1 interrupt, got %d\n", interrupt_count);
        test_fail(1);
        return 1;
    }

    printf("SUCCESS: BARK threshold jump triggered interrupt\n");

    ////////////////////////////////////////////////
    // STEP 3: BITE threshold jump test           //
    // count=100, bite=1000 -> bite=20 -> reset    //
    ////////////////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 3: BITE threshold jump test\n");
    printf("//////////////////////////////////////////////////\n\n");

    /* Call test_pass BEFORE triggering reset */
    printf("Signaling test_pass before triggering reset...\n");
    test_pass(0);

    /* Set initial values with high thresholds */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 100);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 1000);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);

    printf("Set count=100, bite=1000, bark=0xFFFFFFFF\n");

    /* Enable WDT */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);
    printf("WDT enabled\n");

    /* Lower bite threshold below current count to trigger reset */
    printf("Lowering bite threshold to 20...\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 20);

    /* Firmware-provable arming check only; rst_req edge is owned by cocotb. */
    uint32_t bite_thold = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR);
    uint32_t count_armed = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    if (bite_thold != 20) {
        printf("ERROR: bite thold not jumped (got %u)\n", bite_thold);
        test_fail(1);
        return 1;
    }
    if (count_armed < 20) {
        printf("ERROR: count 0x%08x < jumped bite thold 20\n", count_armed);
        test_fail(1);
        return 1;
    }
    printf("CHK-BITE-ARMED: thold=%u count=0x%08x\n", bite_thold, count_armed);

    /* Loop forever - reset should fire and cocotb will verify */
    printf("Waiting for reset (cocotb will verify)...\n");
    while (1) {
        __asm__ volatile("wfi");
    }

    /* Should never reach here */
    return 1;
}
