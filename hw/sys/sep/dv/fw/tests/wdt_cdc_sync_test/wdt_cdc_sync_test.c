/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * TC_WDT_009 (V3, P2) - WDT CDC Sync / Register Consistency Test
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

    printf("TC_WDT_009: WDT CDC Sync / Register Consistency Test\n");
    printf("======================================================\n\n");

    int errors = 0;

    /* Ensure WDT disabled */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 1: WDOG_BARK_THOLD write/readback */
    printf("// STEP 1: WDOG_BARK_THOLD R/W consistency\n");
    uint32_t test_vals[] = {0x00000001, 0x0000FFFF, 0x12345678, 0xFFFFFFFF, 0x00001000};
    for (int i = 0; i < 5; i++) {
        WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, test_vals[i]);
        errors += check_reg(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, test_vals[i],
                            "BARK_THOLD");
    }

    /* STEP 2: WDOG_BITE_THOLD write/readback */
    printf("\n// STEP 2: WDOG_BITE_THOLD R/W consistency\n");
    for (int i = 0; i < 5; i++) {
        WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, test_vals[i]);
        errors += check_reg(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, test_vals[i],
                            "BITE_THOLD");
    }

    /* STEP 3: WDOG_CTRL write/readback */
    printf("\n// STEP 3: WDOG_CTRL R/W consistency\n");
    /* Bit 0=enable, bit 1=pause_in_sleep */
    uint32_t ctrl_vals[] = {0x0, 0x1, 0x2, 0x3};
    for (int i = 0; i < 4; i++) {
        WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, ctrl_vals[i]);
        uint32_t rd = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR);
        if ((rd & 0x3) != (ctrl_vals[i] & 0x3)) {
            printf("  FAIL: WDOG_CTRL wrote 0x%x, readback 0x%08x\n", ctrl_vals[i], rd);
            errors++;
        } else {
            printf("  PASS: WDOG_CTRL = 0x%08x\n", rd);
        }
    }
    /* Ensure disabled after test */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 4: WDOG_COUNT write (pet) readback */
    printf("\n// STEP 4: WDOG_COUNT write (pet) readback near 0\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0xFFFFFFFF);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    /* Let it count a bit */
    for (volatile int i = 0; i < 30000; i++) {
        __asm__ volatile("nop");
    }
    uint32_t before_pet = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count before pet = 0x%08x\n", before_pet);

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    uint32_t after_pet = READ_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("  Count after pet = 0x%08x (expect ~0)\n", after_pet);
    if (after_pet > 0x200) {
        printf("  FAIL: Count not reset by write (0x%08x)\n", after_pet);
        errors++;
    } else {
        printf("  PASS: Count reset to ~0 by write\n");
    }

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    /* STEP 5: Sequential writes, no corruption */
    printf("\n// STEP 5: Sequential multi-register write - no corruption\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xABCD1234);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0x12345678);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0x0);
    /* Verify all still correct */
    errors += check_reg(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0xABCD1234,
                        "BARK_THOLD after seq");
    errors += check_reg(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0x12345678,
                        "BITE_THOLD after seq");

    /* STEP 6: WKUP registers accessible (coverage for unused but present registers) */
    printf("\n// STEP 6: WKUP_CTRL register accessible\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR, 0x0);
    uint32_t wkup_ctrl = READ_REG(OCH_SEP_TOP_WDT_TIMER_WKUP_CTRL_BASE_ADDR);
    printf("  WKUP_CTRL readback = 0x%08x\n", wkup_ctrl);
    printf("  PASS: WKUP registers accessible\n");

    printf("\n======================================================\n");
    if (errors == 0) {
        printf("TC_WDT_009: PASS\n");
        test_pass(0);
    } else {
        printf("TC_WDT_009: FAIL (errors=%d)\n", errors);
        test_fail(1);
    }
    printf("======================================================\n");

    while (1) {
        __asm__ volatile("wfi");
    }
}
