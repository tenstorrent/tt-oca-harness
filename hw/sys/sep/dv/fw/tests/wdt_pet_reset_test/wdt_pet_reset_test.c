/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Pet/Reset Test
 *
 * Verifies watchdog pet operation (write 0 to WDOG_COUNT).
 *
 * Steps:
 * 1. Enable WDT, let count reach ~500
 * 2. Pet (write 0 to WDOG_COUNT) → verify counter resets to ~0
 * 3. Repeat pet at various counts (100, 500, 900)
 * 4. Positive control (bark NMI can fire), then pet below high threshold
 *    and verify no unexpected NMI
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
#include "aon_timer.h"

static volatile int unexpected_nmi = 0;

void wdt_nmi_handler(void) {
    unexpected_nmi++;
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);
}

/* Wait until WDOG_COUNT >= target_count. High thresholds so NMI won't fire. */
static void wait_for_count(uint32_t target) {
    while (READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR) < target) {
        __asm__ volatile("nop");
    }
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Pet/Reset Test\n");
    printf("================================\n\n");

    int errors = 0;

    /* Set up NMI handler to catch unexpected interrupts */
    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    /* Use a high BARK threshold so petting prevents it */
    uint32_t high_bark = 0x00FFFFFF;
    uint32_t high_bite = 0xFFFFFFFF;

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, high_bark);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, high_bite);

    /* STEP 1: Enable and let count reach ~500 */
    printf("// STEP 1: Enable and wait for count ~500\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);
    wait_for_count(500);
    uint32_t pre = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before first pet = 0x%08x\n", pre);

    /* STEP 2: Pet and verify resets to ~0 */
    printf("\n// STEP 2: Pet at count ~500 -> verify resets to ~0\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    uint32_t post = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x\n", post);
    if (post > 0x100) {
        printf("  FAIL: Count not reset by pet (0x%08x > 0x100)\n", post);
        errors++;
    } else {
        printf("  PASS: Pet reset count to ~0\n");
    }

    /* STEP 3: Pet at count=100 */
    printf("\n// STEP 3: Pet at count ~100\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    wait_for_count(100);
    pre = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before pet = 0x%08x\n", pre);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    post = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x\n", post);
    if (post > 0x100) {
        printf("  FAIL: Pet at 100 did not reset count\n");
        errors++;
    } else {
        printf("  PASS: Pet at 100 reset count\n");
    }

    /* STEP 3b: Pet at count=900 */
    printf("\n// STEP 3b: Pet at count ~900\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    wait_for_count(900);
    pre = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before pet = 0x%08x\n", pre);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    post = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x\n", post);
    if (post > 0x100) {
        printf("  FAIL: Pet at 900 did not reset count\n");
        errors++;
    } else {
        printf("  PASS: Pet at 900 reset count\n");
    }

    /* STEP 4: Positive control (NMI can fire), then pet below high threshold */
    printf("\n// STEP 4: Positive control NMI, then pet below high threshold\n");

    /* 4a: Prove bark NMI path works with a low threshold (no pet). */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm |
                  AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm);
    unexpected_nmi = 0;
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 100);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, high_bite);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    int timeout = 2000000;
    while (unexpected_nmi == 0 && timeout-- > 0) {
        __asm__ volatile("nop");
    }
    if (unexpected_nmi == 0) {
        printf("  FAIL: Positive control — NMI did not fire with low bark\n");
        errors++;
    } else {
        printf("  PASS: Positive control — NMI fired (nmi=%d)\n", unexpected_nmi);
    }

    /* Clear/disable before the pet-below-threshold path. */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm |
                  AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm);
    unexpected_nmi = 0;

    /* 4b: Pet well below high bark — must not fire NMI. */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, high_bark);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);
    wait_for_count(5000);
    pre = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    post = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Petted at %u, count after = 0x%08x\n", pre, post);
    for (volatile int i = 0; i < 100000; i++) {
        __asm__ volatile("nop");
    }
    if (unexpected_nmi != 0) {
        printf("  FAIL: NMI fired unexpectedly during pet-below-threshold (nmi=%d)\n",
               unexpected_nmi);
        errors++;
    } else {
        printf("  PASS: No NMI after pet below high bark threshold\n");
    }

    /* STEP 5: Verify counter resumes after pet */
    printf("\n// STEP 5: Counter resumes after pet\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, high_bark);
    uint32_t snap1 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    for (volatile int i = 0; i < 20000; i++) {
        __asm__ volatile("nop");
    }
    uint32_t snap2 = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count t1=0x%08x, t2=0x%08x\n", snap1, snap2);
    if (snap2 <= snap1) {
        printf("  FAIL: Counter not incrementing after pet\n");
        errors++;
    } else {
        printf("  PASS: Counter resumes after pet\n");
    }

    /* Disable */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    printf("\n================================\n");
    if (errors == 0 && unexpected_nmi == 0) {
        printf("WDT Pet/Reset Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT Pet/Reset Test: FAIL (errors=%d, unexpected_nmi=%d)\n", errors, unexpected_nmi);
        test_fail(1);
    }
    printf("================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
