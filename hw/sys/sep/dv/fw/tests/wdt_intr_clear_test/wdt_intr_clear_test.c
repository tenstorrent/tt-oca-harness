/*******************************************************************************
 * TC_WDT_011 (V3, P2) - WDT Interrupt Clear Test
 *
 * Verifies INTR_STATE W1C mechanism:
 * - Bark fires → INTR_STATE[1] sets
 * - Write 1 to INTR_STATE[1] → clears
 * - Interrupt output deasserts
 * - Re-trigger: pet after W1C resets count, count grows back → new posedge
 *
 * Note: prim_edge_detector only fires on posedge of wdog_intr_o.
 * W1C alone does not re-trigger because wdog_intr_o stays HIGH while
 * count >= bark_thold. Re-trigger requires pet (count→0 → wdog_intr_o LOW)
 * then waiting for count to grow back above bark_thold (posedge fires again).
 *
 * Steps:
 * 1. Generate BARK → read INTR_STATE[1]=1, W1C clears it
 * 2. Pet (count=0 → wdog_intr_o LOW) → wait for re-trigger (new posedge)
 * 3. Disable WDT, verify no further triggers
 * 4. INTR_TEST W1C verification
 *
 * Copyright 2025 Tenstorrent Inc.
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "nmi.h"
#include "test_completion.h"

static volatile int nmi_count     = 0;
static volatile int nmi_errors    = 0;
static volatile int phase         = 0;  /* 0=wait first bark, 1=wait re-trigger, 2=done */

void wdt_nmi_handler(void) {
    nmi_count++;

    /* Read INTR_STATE before W1C */
    uint32_t state = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);

    /* Always W1C first to prevent continuous NMI re-entry (level-triggered NMI) */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x2);

    printf("  NMI #%d (phase=%d)\n", nmi_count, phase);

    if (!(state & 0x2)) {
        printf("  FAIL: INTR_STATE[1] not set on NMI #%d\n", nmi_count);
        nmi_errors++;
    } else {
        printf("  PASS: INTR_STATE = 0x%08x (bit 1 set)\n", state);
    }

    if (phase == 0) {
        /* First bark: verify W1C worked, signal main to pet and wait for re-trigger */
        uint32_t after = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        if (after & 0x2) {
            printf("  FAIL: W1C did not clear INTR_STATE (0x%08x)\n", after);
            nmi_errors++;
        } else {
            printf("  PASS: W1C cleared INTR_STATE[1]\n");
        }
        phase = 1;
        /* Main will pet (count=0 → wdog_intr_o LOW), then count grows back → re-trigger */

    } else if (phase == 1) {
        /* Re-trigger from posedge after pet: disable WDT to stop further triggers */
        WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
        printf("  PASS: Re-trigger fired correctly after pet, WDT disabled\n");
        phase = 2;
    }
    /* phase == 2: W1C already done above, no further action needed */
}

int main(void)
{
    sep_outbound_filter_init();

    printf("TC_WDT_011: WDT Interrupt Clear Test\n");
    printf("======================================\n\n");

    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    int errors = 0;

    /* STEP 1: Generate BARK */
    printf("// STEP 1: Generate BARK interrupt\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 2000);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    /* Wait for first bark */
    while (phase == 0) { __asm__ volatile("wfi"); }

    printf("  PASS: First BARK fired (NMI #1)\n");

    /* STEP 2: Pet to bring count below threshold, then wait for re-trigger */
    printf("\n// STEP 2: Pet (count=0) → wait for re-trigger (count grows back above BARK_THOLD)\n");
    /* Pet: reset count to 0 so wdog_intr_o goes LOW → enables posedge re-trigger */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    /* Wait for count to grow back above bark_thold (2000) and fire second NMI */
    while (phase == 1) { __asm__ volatile("wfi"); }

    printf("  PASS: Re-trigger fired (NMI #2)\n");

    /* STEP 3: Verify no further triggers after disable+pet */
    printf("\n// STEP 3: Verify no further triggers after disable+pet\n");
    /* WDT already disabled in phase=1 handler - drain any in-flight CDC pulses */
    for (volatile int i = 0; i < 5000; i++) { __asm__ volatile("nop"); }  /* drain */
    int prev_count = nmi_count;
    for (volatile int i = 0; i < 100000; i++) { __asm__ volatile("nop"); }
    if (nmi_count != prev_count) {
        printf("  FAIL: Spurious NMI after disable+pet (got %d extra)\n", nmi_count - prev_count);
        errors++;
    } else {
        printf("  PASS: No spurious NMI after disable+pet\n");
    }

    /* STEP 4: Manual INTR_STATE W1C with WDT disabled */
    printf("\n// STEP 4: Manual INTR_STATE W1C (via INTR_TEST)\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3);  /* clear any residual */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_TEST_BASE_ADDR, 0x2);   /* inject */
    int prev = nmi_count;
    for (volatile int i = 0; i < 1000000 && nmi_count == prev; i++) { __asm__ volatile("nop"); }

    /* Phase is 2 now, NMI won't be in our phase handler, but will at least read INTR_STATE */
    uint32_t st = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    /* Clear it */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x2);
    uint32_t st2 = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (st2 & 0x2) {
        printf("  FAIL: INTR_STATE[1] not cleared by W1C (0x%08x)\n", st2);
        errors++;
    } else {
        printf("  PASS: W1C clears INTR_STATE[1]\n");
    }

    errors += nmi_errors;

    printf("\n======================================\n");
    if (errors == 0) {
        printf("TC_WDT_011: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_011: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("======================================\n");

    while (1) { __asm__ volatile("wfi"); }
}
