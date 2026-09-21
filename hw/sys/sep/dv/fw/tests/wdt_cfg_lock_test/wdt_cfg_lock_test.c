/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * WDT Config Lock Test
 *
 * Tests that the watchdog config lock functionality works as expected.
 *
 * Test flow:
 * 1. Initialize NMI handler
 * 2. Configure WDT (thresholds, ctrl, etc.)
 * 3. Lock WDT config registers
 * 4. Attempt to write to locked registers, verify failure
 * 5. Pet the watchdog (write 0 to WDOG_COUNT), verify that still works
 * 6. Wait for BARK interrupt, verify that INTR_STATE register is set, and can be cleared by the
 *interrupt handler
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "tb.h"
#include "nmi.h"
#include "test_completion.h"
#include "aon_timer.h"

#define WDOG_BARK_THOLD_DEFAULT 0xFFFF
#define WDOG_BITE_THOLD_DEFAULT 0xFFFFFFFF
#define WDOG_CTRL_DEFAULT AON_TIMER__WDOG_CTRL__ENABLE_bm

uint32_t interrupt_expected;

void wdt_nmi_handler(void) {

    /* Verify that the interrupt is expected */
    if (interrupt_expected == 0x0) {
        printf("ERROR: Unexpected interrupt received! Expected 0x0, got 0x%08x\n",
               interrupt_expected);
        test_fail(1);
        return;
    }

    printf("WDT bark interrupt received\n");

    /* Read back the INTR_STATE register */
    uint32_t intr_state = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if ((intr_state & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) == 0) {
        printf("ERROR: INTR_STATE bark bit not set! got 0x%08x\n", intr_state);
        test_fail(1);
        return;
    }

    printf("INTR_STATE register after interrupt: 0x%08x\n", intr_state);

    WRITE_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);

    /* Read back INTR_STATE register and verify its cleared */
    intr_state = READ_REG(SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if (intr_state != 0x0) {
        printf("ERROR: INTR_STATE register is not cleared! Expected 0x0, got 0x%08x\n", intr_state);
        test_fail(1);
        return;
    }

    printf("INTR_STATE register after clear: 0x%08x\n", intr_state);

    printf("SUCCESS: WDT bark interrupt received\n");

    test_pass(0);

    /* Should never reach here */
    while (1) {
        __asm__ volatile("nop");
    }
}

int main(void) {
    /* Initialize outbound filter to allow testpass mailbox access */
    sep_outbound_filter_init();

    printf("WDT Config Lock Test\n");
    printf("========================\n\n");

    interrupt_expected = 0x0;

    ////////////////////////////////
    // STEP 1: Set up NMI handler //
    ////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 1: Set up NMI handler\n");
    printf("//////////////////////////////////////////////////\n\n");

    nmi_register_handler(wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_lock_vector_reg();

    printf("SUCCESS: NMI handler set up\n");

    //////////////////////////////////////
    // STEP 2: Configure WDT registers  //
    //////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 2: Configure WDT registers\n");
    printf("//////////////////////////////////////////////////\n\n");

    /* Set initial values with high thresholds */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, WDOG_BARK_THOLD_DEFAULT);
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, WDOG_BITE_THOLD_DEFAULT);

    /* Enable WDT */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, WDOG_CTRL_DEFAULT);
    printf("WDT enabled\n");

    ///////////////////////////////////////
    // STEP 3: Lock WDT config registers //
    ///////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 3: Lock WDT config registers\n");
    printf("//////////////////////////////////////////////////\n\n");

    /* Write 0 to WDOG_REGWEN to lock the WDT config registers */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_REGWEN_BASE_ADDR, 0x0);

    //////////////////////////////////////////////////
    // STEP 4: Attempt to write to locked registers //
    //////////////////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 4: Attempt to write to locked registers\n");
    printf("//////////////////////////////////////////////////\n\n");

    /* Attempt to write to locked registers and verify that the write was ignored */
    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, 0x1000);
    uint32_t bark_thold = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR);
    if (bark_thold != WDOG_BARK_THOLD_DEFAULT) {
        printf("ERROR: WDOG_BARK_THOLD register was written to! Expected 0xFFFF, got 0x%08x\n",
               bark_thold);
        test_fail(1);
        return -1;
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, 0x1000);
    uint32_t bite_thold = READ_REG(SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR);
    if (bite_thold != WDOG_BITE_THOLD_DEFAULT) {
        printf("ERROR: WDOG_BITE_THOLD register was written to! Expected 0xFFFFFFFF, got 0x%08x\n",
               bite_thold);
        test_fail(1);
        return -1;
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);
    uint32_t ctrl = READ_REG(SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR);
    if (ctrl != WDOG_CTRL_DEFAULT) {
        printf("ERROR: WDOG_CTRL register was written to! Expected 0x1, got 0x%08x\n", ctrl);
        test_fail(1);
        return -1;
    }

    printf("SUCCESS: Writes to locked registers were ignored\n");

    //////////////////////////////////////////////////////
    // STEP 5: Pet the watchdog (write 0 to WDOG_COUNT) //
    //////////////////////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 5: Pet the watchdog (write 0 to WDOG_COUNT)\n");
    printf("//////////////////////////////////////////////////\n\n");

    uint32_t original_count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    printf("WDOG_COUNT register before pet: 0x%08x\n", original_count);
    if (original_count == 0) {
        printf("ERROR: WDOG_COUNT register is 0! Expected non-zero\n");
        test_fail(1);
        return -1;
    }

    WRITE_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);
    uint32_t count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
    uint32_t variance = 0x100; // Allow for some variance in the count
    if (count > variance) {
        printf("ERROR: WDOG_COUNT register was written to! Expected 0 (+- %d), got 0x%08x\n",
               variance, count);
        test_fail(1);
        return -1;
    }
    printf("WDOG_COUNT register after pet: 0x%08x\n", count);

    printf("SUCCESS: Petted the watchdog\n");

    //////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // STEP 6: Wait for BARK interrupt, verify that INTR_STATE register is set, and can be cleared
    // by the interrupt handler //
    //////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

    printf("\n//////////////////////////////////////////////////\n");
    printf("// STEP 6: Wait for BARK interrupt, verify that INTR_STATE register is set, and can be "
           "cleared by the interrupt handler\n");
    printf("//////////////////////////////////////////////////\n\n");

    interrupt_expected = 1;

    /* Wait for BARK interrupt */
    while (1) {
        uint32_t count = READ_REG(SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR);
        if (count % 0x100 == 0) {
            printf("WDT count: 0x%08x\n", count);
        }
    }

    /* Should never reach here */
    printf("FAIL: BARK interrupt was not received!\n");
    test_fail(1);
    return -1;
}
