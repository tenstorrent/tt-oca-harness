/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT BITE Before BARK Test
 *
 * When BITE_THOLD < BARK_THOLD, prove count reaches BITE without the bark
 * interrupt bit setting (bite ordering). The FAIL-ON path is the firmware
 * count/INTR observe below.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "aon_timer.h"

#define BITE_THOLD_VAL (200u)
#define BARK_THOLD_VAL (5000u)

#define INTR_STATE_CLEAR_ALL \
    (AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm | AON_TIMER__INTR_STATE__WKUP_TIMER_EXPIRED_bm)

int main(void) {
    sep_outbound_filter_init();

    printf("WDT Bite Before Bark Test\n");
    printf("========================================\n\n");

    int errors = 0;

    /* STEP 1: Configure BITE_THOLD < BARK_THOLD */
    printf("// STEP 1: Configure BITE_THOLD(%u) < BARK_THOLD(%u)\n", BITE_THOLD_VAL,
           BARK_THOLD_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, BARK_THOLD_VAL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, BITE_THOLD_VAL);

    /* STEP 2: Verify register read-back */
    printf("// STEP 2: Verify register read-back\n");
    uint32_t bark_rb = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
    uint32_t bite_rb = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR);

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
        printf("  FAIL: BITE(%u) should be < BARK(%u)\n", bite_rb, bark_rb);
        errors++;
    } else {
        printf("  PASS: BITE(%u) < BARK(%u)\n", bite_rb, bark_rb);
    }

    if (errors != 0) {
        printf("WDT Bite Before Bark Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
        while (1) {
            __asm__ volatile("wfi");
        }
    }

    /* STEP 3: Enable near BITE; observe count >= BITE with bark still clear */
    printf("\n// STEP 3: Observe count reach BITE without BARK INTR\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, INTR_STATE_CLEAR_ALL);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, BITE_THOLD_VAL - 16u);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    int reached_bite = 0;
    uint32_t cnt = 0;
    for (int i = 0; i < 2000000; i++) {
        cnt = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        uint32_t intr = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
        if (intr & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) {
            printf("  FAIL: BARK INTR set at count=0x%08x before/at BITE observe\n", cnt);
            errors++;
            break;
        }
        if (cnt >= BITE_THOLD_VAL) {
            reached_bite = 1;
            break;
        }
        __asm__ volatile("nop");
    }

    if (errors == 0 && !reached_bite) {
        printf("  FAIL: Timeout waiting for count >= BITE (%u); last=0x%08x\n", BITE_THOLD_VAL,
               cnt);
        errors++;
    } else if (errors == 0) {
        printf("  PASS: count=0x%08x >= BITE %u with BARK INTR clear\n", cnt, BITE_THOLD_VAL);
    }

    /* STEP 4: Signal before/as bite reset request propagates */
    printf("\n// STEP 4: Signal test result\n");
    if (errors == 0) {
        printf("WDT Bite Before Bark Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT Bite Before Bark Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }

    while (1) {
        __asm__ volatile("wfi");
    }
}
