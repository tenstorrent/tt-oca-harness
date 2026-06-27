/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*******************************************************************************
 * TC_WDT_007 (V3, P2) - WDT LC Escalate Test
 *
 * NOTE: lc_escalate_en_i is permanently tied to lc_ctrl_pkg::Off in
 * sep_wdt_wrap.sv. LC escalate halt is NOT testable from firmware.
 *
 * This test verifies the WDT runs normally (confirming lc_escalate=Off has
 * no effect on normal operation), and documents the limitation.
 *
 * Steps:
 * 1. Enable WDT, verify counter increments normally (lc_escalate=Off)
 * 2. Verify bark interrupt fires normally
 * 3. Report result - pass with documented limitation
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "nmi.h"
#include "test_completion.h"

static volatile int bark_fired = 0;

void wdt_nmi_handler(void) {
    bark_fired++;
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x2);
    printf("  WDT bark NMI received (bark_fired=%d)\n", bark_fired);
}

int main(void)
{
    sep_outbound_filter_init();

    printf("TC_WDT_007: WDT LC Escalate Test\n");
    printf("==================================\n\n");

    printf("NOTE: lc_escalate_en_i is tied to lc_ctrl_pkg::Off in sep_wdt_wrap.sv.\n");
    printf("      LC escalate halt is NOT testable from firmware in SEP integration.\n");
    printf("      This test verifies normal WDT operation with lc_escalate=Off.\n\n");

    int errors = 0;

    /* Set up NMI handler */
    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    /* STEP 1: Verify counter increments normally */
    printf("// STEP 1: Counter increments normally (lc_escalate=Off)\n");

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    for (volatile int i = 0; i < 40000; i++) { __asm__ volatile("nop"); }

    uint32_t cnt = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDT count = 0x%08x (expect non-zero)\n", cnt);
    if (cnt == 0) {
        printf("  FAIL: Counter stuck at 0\n");
        errors++;
    } else {
        printf("  PASS: Counter incrementing normally\n");
    }

    /* STEP 2: Bark fires normally */
    printf("\n// STEP 2: Bark fires normally (lc_escalate=Off, no halt)\n");

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 3000);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    while (bark_fired == 0) { __asm__ volatile("wfi"); }

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    printf("  PASS: Bark fired normally with lc_escalate=Off\n");

    printf("\n// DOCUMENTED LIMITATION: TC_WDT_007 LC escalate halt not testable\n");
    printf("//   sep_wdt_wrap.sv:145: .lc_escalate_en_i ({3{lc_ctrl_pkg::Off}})\n");
    printf("//   Functional halt via lc_escalate requires RTL change or TB backdoor.\n");

    printf("\n==================================\n");
    if (errors == 0) {
        printf("TC_WDT_007: PASS (normal operation verified; escalate halt N/A)\n");
        test_pass(0);
    } else {
        printf("TC_WDT_007: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("==================================\n");

    while (1) { __asm__ volatile("wfi"); }
}
