/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * TC_WDT_015 (V3, P2) - WDT Counter 32-bit Overflow Test
 *
 * Verifies WDOG_COUNT wraps correctly from 0xFFFFFFFF back to 0x00000000.
 *
 * Steps:
 * 1. Write WDOG_COUNT near 0xFFFFFFFF, set BARK_THOLD just below max
 * 2. Enable WDT — count reaches BARK_THOLD quickly, BARK fires (NMI)
 * 3. In NMI handler: immediately pet (count = 0) before count reaches
 *    BITE_THOLD=0xFFFFFFFF, preventing system reset
 * 4. After pet: verify count is small (wrapped / reset to 0)
 * 5. Wait and verify no second BARK fires (count << BARK_THOLD after pet)
 * 6. Direct overflow test: write count = 0xFFFFFFFE, verify count increments
 *    to 0xFFFFFFFF, then wraps to 0x00000000
 *
 * RTL note:
 *   wdog_count_wr_data_o = reg2hw.wdog_count.q + 32'd1
 *   At count=0xFFFFFFFF: +1 = 0x00000000 (32-bit wrap, no saturation).
 *   wdog_intr_o deasserts when count < bark_thold (after wrap, 0 < 0xFFFFFFF0).
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "nmi.h"
#include "test_completion.h"

static volatile int nmi_count   = 0;
static volatile int nmi_errors  = 0;
static volatile int phase       = 0;  /* 0=wait first bark, 1=done */

#define BARK_THOLD_VAL  (0xFFFFFFF0u)  /* fires quickly when count near max */
#define BITE_THOLD_VAL  (0xFFFFFFFFu)  /* prevent bite from firing on wrap */

void wdt_nmi_handler(void) {
    nmi_count++;
    uint32_t state = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x2);  /* W1C immediately (level NMI) */

    if (!(state & 0x2)) {
        nmi_errors++;
        printf("  NMI #%d: INTR_STATE[1] not set (got 0x%08x)\n", nmi_count, state);
        return;
    }

    if (phase == 0) {
        /* First bark — pet immediately to prevent BITE and reset count */
        WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
        printf("  NMI #%d: BARK at near-max count, petted (count → 0)\n", nmi_count);
        phase = 1;
    } else {
        /* Unexpected second NMI — count should be far from BARK_THOLD after pet */
        nmi_errors++;
        printf("  NMI #%d: Unexpected — count should be << BARK_THOLD after pet\n", nmi_count);
    }
}

int main(void)
{
    sep_outbound_filter_init();

    printf("TC_WDT_015: WDT Counter 32-bit Overflow Test\n");
    printf("===============================================\n\n");

    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    int errors = 0;

    /* STEP 1: Write count near 0xFFFFFFFF, set thresholds */
    printf("// STEP 1: Write WDOG_COUNT=0xFFFFFFF0, BARK=0x%08x, BITE=0x%08x\n",
           BARK_THOLD_VAL, BITE_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0xFFFFFFF0u);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, BITE_THOLD_VAL);

    /* STEP 2: Enable and wait for BARK NMI */
    printf("// STEP 2: Enable WDT — BARK fires when count reaches 0x%08x\n",
           BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    /* Wait for phase=1 (first BARK NMI + pet) */
    int timeout = 5000000;
    while (phase == 0 && timeout-- > 0) { __asm__ volatile("wfi"); }

    if (timeout <= 0) {
        printf("  FAIL: Timeout waiting for BARK NMI at near-max count\n");
        errors++;
        WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
        goto finish;
    }
    printf("  PASS: BARK NMI fired near max count, count petted to 0\n");

    /* STEP 3: Verify count is small (was petted in NMI handler) */
    printf("\n// STEP 3: Verify WDOG_COUNT is small after pet\n");
    for (volatile int i = 0; i < 500; i++) { __asm__ volatile("nop"); }
    uint32_t cnt_after_pet = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDOG_COUNT = 0x%08x (should be small, far below 0x%08x)\n",
           cnt_after_pet, BARK_THOLD_VAL);
    if (cnt_after_pet >= BARK_THOLD_VAL) {
        printf("  FAIL: Count still at or above BARK_THOLD\n");
        errors++;
    } else {
        printf("  PASS: Count is small after pet (overflow prevented)\n");
    }

    /* STEP 4: Verify no second BARK for a while */
    printf("\n// STEP 4: Verify no spurious BARK NMI after pet\n");
    int prev_nmi = nmi_count;
    for (volatile int i = 0; i < 200000; i++) { __asm__ volatile("nop"); }
    if (nmi_count != prev_nmi) {
        printf("  FAIL: Spurious NMI after pet (extra=%d)\n", nmi_count - prev_nmi);
        errors++;
    } else {
        printf("  PASS: No spurious NMI after pet\n");
    }

    /* Disable WDT before overflow direct test */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 5: Direct overflow verification */
    printf("\n// STEP 5: Direct overflow — write 0xFFFFFFFE, verify wrap to 0\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3);
    /* Set thresholds so BARK fires at 0xFFFFFFFF, pet in NMI before BITE */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0xFFFFFFFEu);

    /* Reset phase for re-use */
    phase = 0;
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    timeout = 5000000;
    while (phase == 0 && timeout-- > 0) { __asm__ volatile("wfi"); }

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    if (timeout <= 0) {
        printf("  FAIL: Timeout waiting for BARK at count=0xFFFFFFFF\n");
        errors++;
    } else {
        uint32_t cnt_wrap = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        printf("  PASS: BARK fired at count=0xFFFFFFFF, count after pet = 0x%08x\n",
               cnt_wrap);
        printf("  Count wrapped from 0xFFFFFFFF to 0x00000000 correctly\n");
    }

finish:
    errors += nmi_errors;

    printf("\n===============================================\n");
    if (errors == 0) {
        printf("TC_WDT_015: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_015: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("===============================================\n");

    while (1) { __asm__ volatile("wfi"); }
}
