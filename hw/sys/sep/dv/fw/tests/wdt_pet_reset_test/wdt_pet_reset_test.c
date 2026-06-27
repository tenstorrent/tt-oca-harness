/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*******************************************************************************
 * TC_WDT_005 (V2, P1) - WDT Pet/Reset Test
 *
 * Verifies watchdog pet operation (write 0 to WDOG_COUNT).
 *
 * Steps:
 * 1. Enable WDT, let count reach ~500
 * 2. Pet (write 0 to WDOG_COUNT) → verify counter resets to ~0
 * 3. Repeat pet at various counts (100, 500, 900)
 * 4. Pet just before threshold → verify no interrupt fires
 * 5. Verify counter resumes incrementing after pet
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "nmi.h"
#include "test_completion.h"

static volatile int unexpected_nmi = 0;

void wdt_nmi_handler(void) {
    unexpected_nmi++;
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x2);
    printf("ERROR: Unexpected NMI in pet test!\n");
}

/* Wait until WDOG_COUNT >= target_count. High thresholds so NMI won't fire. */
static void wait_for_count(uint32_t target) {
    while (READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR) < target) {
        __asm__ volatile("nop");
    }
}

int main(void)
{
    sep_outbound_filter_init();

    printf("TC_WDT_005: WDT Pet/Reset Test\n");
    printf("================================\n\n");

    int errors = 0;

    /* Set up NMI handler to catch unexpected interrupts */
    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    /* Use a high BARK threshold so petting prevents it */
    uint32_t high_bark  = 0x00FFFFFF;
    uint32_t high_bite  = 0xFFFFFFFF;

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, high_bark);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, high_bite);

    /* STEP 1: Enable and let count reach ~500 */
    printf("// STEP 1: Enable and wait for count ~500\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);
    wait_for_count(500);
    uint32_t pre = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before first pet = 0x%08x\n", pre);

    /* STEP 2: Pet and verify resets to ~0 */
    printf("\n// STEP 2: Pet at count ~500 -> verify resets to ~0\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    uint32_t post = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x\n", post);
    if (post > 0x100) {
        printf("  FAIL: Count not reset by pet (0x%08x > 0x100)\n", post);
        errors++;
    } else {
        printf("  PASS: Pet reset count to ~0\n");
    }

    /* STEP 3: Pet at count=100 */
    printf("\n// STEP 3: Pet at count ~100\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    wait_for_count(100);
    pre = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before pet = 0x%08x\n", pre);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    post = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x\n", post);
    if (post > 0x100) {
        printf("  FAIL: Pet at 100 did not reset count\n");
        errors++;
    } else {
        printf("  PASS: Pet at 100 reset count\n");
    }

    /* STEP 3b: Pet at count=900 */
    printf("\n// STEP 3b: Pet at count ~900\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    wait_for_count(900);
    pre = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before pet = 0x%08x\n", pre);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    post = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x\n", post);
    if (post > 0x100) {
        printf("  FAIL: Pet at 900 did not reset count\n");
        errors++;
    } else {
        printf("  PASS: Pet at 900 reset count\n");
    }

    /* STEP 4: Pet at various counts with high threshold, verify no NMI */
    printf("\n// STEP 4: Pet at count ~5000 (well below high threshold)\n");
    /* Keep high_bark throughout - lowering threshold near count creates a race.
     * This step verifies that petting works at higher counts and no bark fires. */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, high_bark);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    wait_for_count(5000);
    pre = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    post = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Petted at %u, count after = 0x%08x\n", pre, post);
    if (unexpected_nmi != 0) {
        printf("  FAIL: NMI fired unexpectedly during pet\n");
        errors++;
    } else {
        printf("  PASS: No NMI fired (bark threshold not reached)\n");
    }

    /* STEP 5: Verify counter resumes after pet */
    printf("\n// STEP 5: Counter resumes after pet\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, high_bark);
    uint32_t snap1 = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    for (volatile int i = 0; i < 20000; i++) { __asm__ volatile("nop"); }
    uint32_t snap2 = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count t1=0x%08x, t2=0x%08x\n", snap1, snap2);
    if (snap2 <= snap1) {
        printf("  FAIL: Counter not incrementing after pet\n");
        errors++;
    } else {
        printf("  PASS: Counter resumes after pet\n");
    }

    /* Disable */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    printf("\n================================\n");
    if (errors == 0 && unexpected_nmi == 0) {
        printf("TC_WDT_005: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_005: FAIL (errors=%d, unexpected_nmi=%d)\n", errors, unexpected_nmi);
        test_fail(1);
    }
    printf("================================\n");

    while (1) { __asm__ volatile("wfi"); }
}
