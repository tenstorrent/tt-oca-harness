/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * TC_WDT_014 (V3, P2) - WDT BITE Before BARK Test
 *
 * Verifies that when BITE_THOLD < BARK_THOLD, the HW accepts the inverted
 * threshold ordering and BITE_THOLD is correctly written and read back.
 *
 * This test verifies:
 *   1. BARK_THOLD and BITE_THOLD registers accept BITE < BARK configuration
 *   2. Read-back values are correct
 *   3. The WDT counter dynamically advances past BITE_THOLD (the condition that
 *      asserts wdog_reset_req_o) while remaining below BARK_THOLD, observed by
 *      polling WDOG_COUNT.
 *
 * Note: the BITE reset request (wdog_reset_req_o) is not wired to a functional
 * reset in this integration, so we cannot observe a CPU reset. Once the counter
 * is seen to cross BITE, the WDT is disabled before it can reach BARK, so
 * BARK's NMI cannot clobber the PASS result. The count-based check is
 * frequency-invariant; its race margin is smallest at the 800 MHz silicon
 * target.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define BITE_THOLD_VAL (200u)
#define BARK_THOLD_VAL (5000u)

int main(void) {
    sep_outbound_filter_init();

    printf("TC_WDT_014: WDT Bite Before Bark Test\n");
    printf("========================================\n\n");

    int errors = 0;

    /* STEP 1: Configure BITE_THOLD(200) < BARK_THOLD(5000) */
    printf("// STEP 1: Configure BITE_THOLD(%u) < BARK_THOLD(%u)\n", BITE_THOLD_VAL,
           BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3); /* clear residual */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, BITE_THOLD_VAL);

    /* STEP 2: Verify register read-back */
    printf("// STEP 2: Verify register read-back\n");
    uint32_t bark_rb = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
    uint32_t bite_rb = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR);

    if (bark_rb != BARK_THOLD_VAL) {
        printf("  FAIL: BARK_THOLD read back 0x%08x (expected 0x%08x)\n", bark_rb, BARK_THOLD_VAL);
        errors++;
    } else {
        printf("  PASS: BARK_THOLD = %u\n", bark_rb);
    }

    if (bite_rb != BITE_THOLD_VAL) {
        printf("  FAIL: BITE_THOLD read back 0x%08x (expected 0x%08x)\n", bite_rb, BITE_THOLD_VAL);
        errors++;
    } else {
        printf("  PASS: BITE_THOLD = %u\n", bite_rb);
    }

    if (bite_rb >= bark_rb) {
        printf("  FAIL: BITE(%u) should be < BARK(%u) — inverted ordering not accepted\n", bite_rb,
               bark_rb);
        errors++;
    } else {
        printf("  PASS: BITE(%u) < BARK(%u) — inverted ordering accepted\n", bite_rb, bark_rb);
    }

    /* STEP 3: Enable the WDT and dynamically observe the counter cross
     * BITE_THOLD -- the condition that asserts wdog_reset_req_o -- then disable
     * it well short of BARK_THOLD. The BITE reset is not wired to a functional
     * reset here, so if the WDT were left armed the counter would reach BARK and
     * fire wdog_intr_o as an NMI that clobbers the PASS result (fw_pass 1->0).
     * Polling WDOG_COUNT is frequency-invariant (it advances on the WDT clock)
     * and proves dynamic BITE operation without racing BARK. */
    printf("\n// STEP 3: Enable WDT; observe counter cross BITE=%u, stop before BARK=%u\n",
           BITE_THOLD_VAL, BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    uint32_t observed_count = 0u;
    /* Stop once the counter has clearly crossed BITE, staying far below BARK. */
    const uint32_t stop_at = BITE_THOLD_VAL + 300u; /* 500 << BARK (5000) */
    int poll_guard = 2000000;
    do {
        observed_count = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    } while (observed_count < stop_at && observed_count < BARK_THOLD_VAL && --poll_guard > 0);

    /* Disable immediately so BARK cannot fire and clobber the result. */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0); /* reset counter */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3); /* clear pending bark/bite */

    /* Dynamic checks (count-based, frequency-invariant): */
    if (observed_count < BITE_THOLD_VAL) {
        printf("  FAIL: counter %u never reached BITE_THOLD %u (WDT not counting)\n",
               observed_count, BITE_THOLD_VAL);
        errors++;
    } else {
        printf("  PASS: counter reached %u (>= BITE %u) -- wdog_reset_req_o condition met\n",
               observed_count, BITE_THOLD_VAL);
    }
    if (observed_count >= BARK_THOLD_VAL) {
        printf("  FAIL: counter %u reached BARK_THOLD %u before disable (timing race)\n",
               observed_count, BARK_THOLD_VAL);
        errors++;
    } else {
        printf("  PASS: counter %u < BARK %u -- BITE observed before BARK\n", observed_count,
               BARK_THOLD_VAL);
    }

    /* STEP 4: Signal test result */
    printf("\n// STEP 4: Signal test result\n");

    if (errors == 0) {
        printf("TC_WDT_014: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_014: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }

    /* WDT disabled above (bite-reset unwired); idle here. */
    while (1) {
        __asm__ volatile("wfi");
    }
}
