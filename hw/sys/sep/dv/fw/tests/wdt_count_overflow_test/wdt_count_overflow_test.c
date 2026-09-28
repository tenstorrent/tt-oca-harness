/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Counter 32-bit Overflow Test
 *
 * Verifies WDOG_COUNT wraps correctly from 0xFFFFFFFF back to 0x00000000.
 *
 * Steps:
 * 1. Write WDOG_COUNT near 0xFFFFFFFF, set BARK_THOLD just below max
 * 2. Enable WDT — count reaches BARK_THOLD quickly, BARK fires (NMI)
 * 3. In NMI handler: immediately pet (count = 0) before count reaches
 * BITE_THOLD=0xFFFFFFFF, preventing system reset
 * 4. After pet: verify count is small (far below BARK_THOLD)
 * 5. Wait and verify no second BARK fires (count << BARK_THOLD after pet)
 * 6. Direct overflow: sample FE→FF (bark at FF expected), disable before bite,
 * then one more enable tick to wrap FF→~0 without software pet
 *
 * RTL note:
 * wdog_count_wr_data_o = reg2hw.wdog_count.q + 32'd1
 * At count=0xFFFFFFFF: +1 = 0x00000000 (32-bit wrap, no saturation).
 * bark/bite use count >= thold on the same incr that advances the counter.
 * Free-running with bark=bite=0xFFFFFFFF and no pet level-reasserts bark and
 * pulses bite every AON tick at FF — that hangs this TB; STEP 5 avoids it.
 *
 ******************************************************************************/

#include "aon_timer.h"
#include "nmi.h"
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include <stdint.h>
#include <stdio.h>

static volatile int nmi_count = 0;
static volatile int nmi_errors = 0;
/* 0=near-max bark+pet, 1=idle, 2=wrap tick, 3=FE→FF climb (bark at FF OK) */
static volatile int phase = 0;
static volatile int wrap_bark_seen = 0;
static volatile uint32_t count_after_wrap_bark = 0xFFFFFFFFu;

#define BARK_THOLD_VAL (0xFFFFFFF0u) /* fires quickly when count near max */
#define BITE_THOLD_VAL (0xFFFFFFFFu) /* above near-max bark window (STEPS 1–4) */

#define INTR_STATE_CLEAR_ALL \
    (AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm | AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm)

void wdt_nmi_handler(void) {
    nmi_count++;
    uint32_t state = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm); /* W1C immediately */

    if (!(state & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm)) {
        nmi_errors++;
        printf("  NMI #%d: INTR_STATE bark not set (got 0x%08x)\n", nmi_count, state);
        return;
    }

    if (phase == 0) {
        /* First bark — pet immediately to prevent BITE and reset count */
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
        printf("  NMI #%d: BARK at near-max count, petted (count → 0)\n", nmi_count);
        phase = 1;
    } else if (phase == 3) {
        /*
         * 5a climb: FE→FF with bark_thold=FF fires bark on the same incr that
         * lands on FF (count >= thold). Clear only; main disables on sample.
         * No pet (would hide the FF sample) and no printf (level-bark UART risk).
         */
        __asm__ volatile("fence" ::: "memory");
    } else if (phase == 2) {
        /*
         * Wrap tick: bark and wrap share the incr at count==FF. Disable so
         * level bark cannot reassert; never software-pet (would fabricate wrap).
         * No printf here — UART in NMI can stall progress under level bark.
         */
        count_after_wrap_bark = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
        wrap_bark_seen = 1;
        __asm__ volatile("fence" ::: "memory");
    } else {
        /* Unexpected second NMI — count should be far from BARK_THOLD after pet */
        nmi_errors++;
        printf("  NMI #%d: Unexpected — count should be << BARK_THOLD after pet\n", nmi_count);
    }
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Counter 32-bit Overflow Test\n");
    printf("===============================================\n\n");

    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    int errors = 0;

    /* STEP 1: Write count near 0xFFFFFFFF, set thresholds */
    printf("// STEP 1: Write WDOG_COUNT=0xFFFFFFF0, BARK=0x%08x, BITE=0x%08x\n", BARK_THOLD_VAL,
           BITE_THOLD_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0xFFFFFFF0u);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, BARK_THOLD_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, BITE_THOLD_VAL);

    /* STEP 2: Enable and wait for BARK NMI */
    printf("// STEP 2: Enable WDT — BARK fires when count reaches 0x%08x\n", BARK_THOLD_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    /* Wait for phase=1 (first BARK NMI + pet) */
    int timeout = 5000000;
    while (phase == 0 && timeout-- > 0) {
        __asm__ volatile("wfi");
    }

    if (timeout <= 0) {
        printf("  FAIL: Timeout waiting for BARK NMI at near-max count\n");
        errors++;
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
        goto finish;
    }
    printf("  PASS: BARK NMI fired near max count, count petted to 0\n");

    /* STEP 3: Verify count is small (was petted in NMI handler) */
    printf("\n// STEP 3: Verify WDOG_COUNT is small after pet\n");
    for (volatile int i = 0; i < 500; i++) {
        __asm__ volatile("nop");
    }
    uint32_t cnt_after_pet = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  WDOG_COUNT = 0x%08x (should be small, far below 0x%08x)\n", cnt_after_pet,
           BARK_THOLD_VAL);
    if (cnt_after_pet >= BARK_THOLD_VAL) {
        printf("  FAIL: Count still at or above BARK_THOLD\n");
        errors++;
    } else {
        printf("  PASS: Count is small after pet (overflow prevented)\n");
    }

    /* STEP 4: Verify no second BARK for a while (bounded — long nop loops
     * burn wall time under this TB's outbound-mailbox UART path). */
    printf("\n// STEP 4: Verify no spurious BARK NMI after pet\n");
    int prev_nmi = nmi_count;
    for (volatile int i = 0; i < 20000; i++) {
        __asm__ volatile("nop");
    }
    if (nmi_count != prev_nmi) {
        printf("  FAIL: Spurious NMI after pet (extra=%d)\n", nmi_count - prev_nmi);
        errors++;
    } else {
        printf("  PASS: No spurious NMI after pet\n");
    }

    /* Disable WDT before overflow direct test */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /*
     * STEP 5: Direct overflow without free-running at FF with bark=bite=FF.
     *
     * 5a) FE→FF: the incr that lands on FF also satisfies count>=bark (FF), so
     * bark may fire; phase==3 accepts that. Disable as soon as FF is
     * sampled (before the wrap/bite incr). Bite also arms at FF; disable
     * before the next tick.
     * 5b) FF→0: one enable tick; bark+wrap (+bite pulse) share that incr.
     * phase==2 NMI disables immediately and must not pet.
     */
    printf("\n// STEP 5: Direct overflow — FE→FF then one-tick wrap to ~0\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0xFFFFFFFEu);

    /* 5a: climb to FF, then stop before wrap/bite */
    phase = 3; /* bark at FF is expected; do not pet or score as error */
    int seen_fe = 0;
    int seen_ff = 0;
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    for (int i = 0; i < 5000000; i++) {
        uint32_t c = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (c == 0xFFFFFFFEu) {
            seen_fe = 1;
        }
        if (c == 0xFFFFFFFFu) {
            seen_ff = 1;
            WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
            printf("  Observed count=0xFFFFFFFF (disabled before wrap/bite tick)\n");
            break;
        }
        __asm__ volatile("nop");
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    if (!seen_ff) {
        printf("  FAIL: Never sampled count==0xFFFFFFFF (seen_fe=%d)\n", seen_fe);
        errors++;
        goto finish;
    }

    /* Ensure we are parked at FF before the wrap tick */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);

    wrap_bark_seen = 0;
    count_after_wrap_bark = 0xFFFFFFFFu;
    phase = 2;
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    timeout = 5000000;
    while (!wrap_bark_seen && timeout-- > 0) {
        uint32_t c = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        /* Poll path: wrap may be visible before/without relying on NMI flag alone
         */
        if (c < 0x100u) {
            break;
        }
        __asm__ volatile("nop");
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    uint32_t cnt_wrap = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    if (wrap_bark_seen) {
        cnt_wrap = count_after_wrap_bark;
        printf("  Wrap bark NMI: count after bark/disable = 0x%08x\n", cnt_wrap);
    } else {
        printf("  Wrap observe (poll): count = 0x%08x\n", cnt_wrap);
    }

    if (cnt_wrap >= 0x100u) {
        printf("  FAIL: No free-running wrap to ~0 (count=0x%08x, "
               "wrap_bark_seen=%d)\n",
               cnt_wrap, wrap_bark_seen);
        errors++;
    } else {
        printf("  PASS: Hardware wrap FF→0x%08x without software pet\n", cnt_wrap);
    }

finish:
    errors += nmi_errors;

    printf("\n===============================================\n");
    if (errors == 0) {
        printf("WDT Counter 32-bit Overflow Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT Counter 32-bit Overflow Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("===============================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
