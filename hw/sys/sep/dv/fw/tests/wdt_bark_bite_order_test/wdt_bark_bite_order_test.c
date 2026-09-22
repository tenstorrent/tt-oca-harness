/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Bark/Bite Order Test
 *
 * Verifies BARK fires before BITE when BARK_THOLD < BITE_THOLD,
 * then signals test_pass before triggering BITE reset (cocotb verifies).
 *
 * Steps:
 * 1. Set BARK_THOLD < BITE_THOLD, count to BARK → verify BARK NMI fires first
 * 2. Confirm BITE has not fired yet
 * 3. Signal test_pass, then let BITE fire (cocotb verifies reset request)
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

static volatile int bark_count = 0;

void wdt_nmi_handler(void) {
    bark_count++;
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);
    printf("  BARK NMI #%d received\n", bark_count);
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Bark/Bite Order Test\n");
    printf("======================================\n\n");

    /* Set up NMI handler for BARK */
    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    int errors = 0;

    /* STEP 1: BARK_THOLD < BITE_THOLD - bark fires first */
    printf("// STEP 1: BARK(3000) < BITE(8000) - verify bark fires before bite\n");

    uint32_t bark_thold = 3000;
    uint32_t bite_thold = 8000;

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, bark_thold);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, bite_thold);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    /* Wait for BARK NMI */
    while (bark_count == 0) {
        __asm__ volatile("wfi");
    }

    uint32_t cnt_at_bark = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  BARK NMI fired at count ~0x%08x (thold=%u)\n", cnt_at_bark, bark_thold);

    /* Disable WDT to stop before BITE */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 2: Verify bark fired at correct threshold */
    printf("\n// STEP 2: Verify BARK fired, BITE did not\n");
    if (bark_count != 1) {
        printf("  FAIL: Expected 1 bark, got %d\n", bark_count);
        errors++;
    } else {
        printf("  PASS: Exactly 1 BARK NMI fired\n");
    }

    /* Verify count was past bark but still below bite at the sample. */
    if (cnt_at_bark < bark_thold) {
        printf("  FAIL: count 0x%08x < bark_thold %u at bark sample\n", cnt_at_bark, bark_thold);
        errors++;
    } else if (cnt_at_bark >= bite_thold) {
        printf("  FAIL: count 0x%08x >= bite_thold %u at bark sample\n", cnt_at_bark, bite_thold);
        errors++;
    } else {
        printf("  PASS: count 0x%08x in [%u, %u) at bark (bite not reached)\n", cnt_at_bark,
               bark_thold, bite_thold);
    }

    /* Signal pass before triggering BITE (BITE causes system reset) */
    printf("\n// Signaling PASS before triggering BITE reset\n");
    if (errors == 0) {
        printf("WDT Bark/Bite Order Test: PASS (bark fires before bite)\n");
        test_pass(0);
    } else {
        printf("WDT Bark/Bite Order Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }

    /* STEP 3: Let BITE fire - cocotb verifies reset request */
    printf("\n// STEP 3: Trigger BITE (cocotb will verify reset request)\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF); /* bark won't fire again */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 200);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 100);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    /* Loop - BITE reset will fire */
    while (1) {
        __asm__ volatile("wfi");
    }
}
