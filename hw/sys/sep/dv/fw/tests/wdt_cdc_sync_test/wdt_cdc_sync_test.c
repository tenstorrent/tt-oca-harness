/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT CDC Sync / Register Consistency Test
 *
 * Verifies that register writes to WDT registers (in SYS domain) propagate
 * correctly through CDC synchronization to the AON domain and are readable
 * back via the SYS-domain register shadow.
 *
 * Steps:
 * 1. Write WDOG_BARK_THOLD, read back - verify value
 * 2. Write WDOG_BITE_THOLD, read back - verify value
 * 3. Write WDOG_CTRL (enable, pause_in_sleep), read back
 * 4. Write WDOG_COUNT (pet), read back near 0
 * 5. Write multiple registers in sequence, verify no corruption
 *
 * Note: True CDC delay measurement not possible from firmware.
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"
#include "aon_timer.h"

#define WDOG_CTRL_FIELD_MASK \
    (AON_TIMER__WDOG_CTRL__ENABLE_bm | AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm)

static int check_reg(uint32_t addr, uint32_t expected, const char *name) {
    uint32_t val = READ_REG(addr);
    if (val != expected) {
        printf("  FAIL: %s = 0x%08x, expected 0x%08x\n", name, val, expected);
        return 1;
    }
    printf("  PASS: %s = 0x%08x\n", name, val);
    return 0;
}

int main(void) {
    sep_outbound_filter_init();

    printf("WDT CDC Sync / Register Consistency Test\n");
    printf("======================================================\n\n");

    int errors = 0;

    /* Ensure WDT disabled */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 1: WDOG_BARK_THOLD write/readback */
    printf("// STEP 1: WDOG_BARK_THOLD R/W consistency\n");
    uint32_t test_vals[] = {0x00000001, 0x0000FFFF, 0x12345678, 0xFFFFFFFF, 0x00001000};
    for (int i = 0; i < 5; i++) {
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, test_vals[i]);
        errors +=
            check_reg(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, test_vals[i], "BARK_THOLD");
    }

    /* STEP 2: WDOG_BITE_THOLD write/readback */
    printf("\n// STEP 2: WDOG_BITE_THOLD R/W consistency\n");
    for (int i = 0; i < 5; i++) {
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, test_vals[i]);
        errors +=
            check_reg(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, test_vals[i], "BITE_THOLD");
    }

    /* STEP 3: WDOG_CTRL write/readback */
    printf("\n// STEP 3: WDOG_CTRL R/W consistency\n");
    uint32_t ctrl_vals[] = {
        0x0,
        AON_TIMER__WDOG_CTRL__ENABLE_bm,
        AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm,
        (AON_TIMER__WDOG_CTRL__ENABLE_bm | AON_TIMER__WDOG_CTRL__PAUSE_IN_SLEEP_bm),
    };
    for (int i = 0; i < 4; i++) {
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, ctrl_vals[i]);
        uint32_t rd = READ_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR);
        if ((rd & WDOG_CTRL_FIELD_MASK) != (ctrl_vals[i] & WDOG_CTRL_FIELD_MASK)) {
            printf("  FAIL: WDOG_CTRL wrote 0x%x, readback 0x%08x\n", ctrl_vals[i], rd);
            errors++;
        } else {
            printf("  PASS: WDOG_CTRL = 0x%08x\n", rd);
        }
    }
    /* Ensure disabled after test */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 4: WDOG_COUNT write (pet) readback */
    printf("\n// STEP 4: WDOG_COUNT write (pet) readback near 0\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm);

    /* Wait until count has advanced (pet proof needs non-trivial before_pet). */
    uint32_t before_pet = 0;
    int advanced = 0;
    for (int i = 0; i < 2000000; i++) {
        before_pet = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (before_pet > 0x40u) {
            advanced = 1;
            break;
        }
        __asm__ volatile("nop");
    }
    printf("  Count before pet = 0x%08x\n", before_pet);
    if (!advanced) {
        printf("  FAIL: Count did not advance before pet (stuck at 0x%08x)\n", before_pet);
        errors++;
    } else {
        WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
        uint32_t after_pet = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        printf("  Count after pet = 0x%08x (expect ~0)\n", after_pet);
        if (after_pet > 0x200u || after_pet >= before_pet) {
            printf("  FAIL: Pet did not reduce count (before=0x%08x after=0x%08x)\n", before_pet,
                   after_pet);
            errors++;
        } else {
            printf("  PASS: Count reset to ~0 by write (was 0x%08x)\n", before_pet);
        }
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 5: Sequential writes, no corruption */
    printf("\n// STEP 5: Sequential multi-register write - no corruption\n");
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xABCD1234);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0x12345678);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    /* Verify all still correct */
    errors +=
        check_reg(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xABCD1234, "BARK_THOLD after seq");
    errors +=
        check_reg(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0x12345678, "BITE_THOLD after seq");

    /* STEP 6: WKUP_CTRL non-zero pattern then clear (dead-bus 0 must fail) */
    printf("\n// STEP 6: WKUP_CTRL non-zero write/readback then clear\n");
    uint32_t wkup_pat =
        AON_TIMER__WKUP_CTRL__ENABLE_bm | ((uint32_t)0x5Au << AON_TIMER__WKUP_CTRL__PRESCALER_bp);
    uint32_t wkup_mask = AON_TIMER__WKUP_CTRL__ENABLE_bm | AON_TIMER__WKUP_CTRL__PRESCALER_bm;
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, wkup_pat);
    uint32_t wkup_ctrl = READ_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR);
    printf("  WKUP_CTRL wrote 0x%08x, readback = 0x%08x\n", wkup_pat, wkup_ctrl);
    if ((wkup_ctrl & wkup_mask) != (wkup_pat & wkup_mask)) {
        printf("  FAIL: WKUP_CTRL non-zero pattern mismatch\n");
        errors++;
    } else {
        printf("  PASS: WKUP_CTRL non-zero pattern retained\n");
    }
    WRITE_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, 0x0);
    wkup_ctrl = READ_REG(SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR);
    if ((wkup_ctrl & wkup_mask) != 0) {
        printf("  FAIL: WKUP_CTRL not cleared (0x%08x)\n", wkup_ctrl);
        errors++;
    } else {
        printf("  PASS: WKUP_CTRL cleared after write 0\n");
    }

    printf("\n======================================================\n");
    if (errors == 0) {
        printf("WDT CDC Sync / Register Consistency Test: PASS\n");
        test_pass(0);
    } else {
        printf("WDT CDC Sync / Register Consistency Test: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("======================================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
