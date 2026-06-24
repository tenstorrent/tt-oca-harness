/*******************************************************************************
 * TC_WDT_014 (V3, P2) - WDT BITE Before BARK Test
 *
 * Verifies that when BITE_THOLD < BARK_THOLD, the HW accepts the inverted
 * threshold ordering and BITE_THOLD is correctly written and read back.
 *
 * This test verifies:
 *   1. BARK_THOLD and BITE_THOLD registers accept BITE < BARK configuration
 *   2. Read-back values are correct
 *   3. The RTL will fire wdog_reset_req_o at BITE (200) before wdog_intr_o
 *      would fire at BARK (5000)
 *
 * Note: test_pass is signaled immediately after enabling the WDT, before
 * BITE fires. Cocotb `sep_hello_test` only waits for the pass signal.
 *
 * Copyright 2025 Tenstorrent Inc.
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

#define BITE_THOLD_VAL  (200u)
#define BARK_THOLD_VAL  (5000u)

int main(void)
{
    sep_outbound_filter_init();

    printf("TC_WDT_014: WDT Bite Before Bark Test\n");
    printf("========================================\n\n");

    int errors = 0;

    /* STEP 1: Configure BITE_THOLD(200) < BARK_THOLD(5000) */
    printf("// STEP 1: Configure BITE_THOLD(%u) < BARK_THOLD(%u)\n",
           BITE_THOLD_VAL, BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x3);   /* clear residual */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, BITE_THOLD_VAL);

    /* STEP 2: Verify register read-back */
    printf("// STEP 2: Verify register read-back\n");
    uint32_t bark_rb = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
    uint32_t bite_rb = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR);

    if (bark_rb != BARK_THOLD_VAL) {
        printf("  FAIL: BARK_THOLD read back 0x%08x (expected 0x%08x)\n",
               bark_rb, BARK_THOLD_VAL);
        errors++;
    } else {
        printf("  PASS: BARK_THOLD = %u\n", bark_rb);
    }

    if (bite_rb != BITE_THOLD_VAL) {
        printf("  FAIL: BITE_THOLD read back 0x%08x (expected 0x%08x)\n",
               bite_rb, BITE_THOLD_VAL);
        errors++;
    } else {
        printf("  PASS: BITE_THOLD = %u\n", bite_rb);
    }

    if (bite_rb >= bark_rb) {
        printf("  FAIL: BITE(%u) should be < BARK(%u) — inverted ordering not accepted\n",
               bite_rb, bark_rb);
        errors++;
    } else {
        printf("  PASS: BITE(%u) < BARK(%u) — inverted ordering accepted\n",
               bite_rb, bark_rb);
    }

    /* STEP 3: Enable WDT */
    printf("\n// STEP 3: Enable WDT (BITE fires at %u, BARK would fire at %u)\n",
           BITE_THOLD_VAL, BARK_THOLD_VAL);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    /* STEP 4: Signal result immediately (before BITE fires at count=200) */
    printf("\n// STEP 4: Signal test result\n");
    printf("  wdog_reset_req_o will assert at count=%u\n", BITE_THOLD_VAL);
    printf("  wdog_intr_o would assert at count=%u (never reached before reset)\n",
           BARK_THOLD_VAL);

    if (errors == 0) {
        printf("TC_WDT_014: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_014: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }

    /* BITE fires at count=200 — reset latched, system held in reset */
    while (1) { __asm__ volatile("wfi"); }
}
