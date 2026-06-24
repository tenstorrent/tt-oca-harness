/*******************************************************************************
 * NMI Sanity Test - Non-Maskable Interrupt Mechanism Verification
 *
 * This test verifies the NMI (Non-Maskable Interrupt) mechanism on the VeeR CPU:
 * - NMI vector address alignment (must be 256-byte aligned)
 * - Default SEP_NMI_VEC register value
 * - NMI vector register write/read
 * - NMI vector lock mechanism (sticky lock prevents further writes)
 * - NMI triggers correctly and jumps to registered handler
 *
 * Test flow:
 * 1. Register NMI handler
 * 2. Verify NMI trampoline is 256-byte aligned
 * 3. Verify default SEP_NMI_VEC value
 * 4. Set NMI vector via register
 * 5. Lock NMI vector register
 * 6. Verify lock is set
 * 7. Test that lock prevents writes
 * 8. Trigger NMI using WDT bark interrupt
 * 9. NMI handler verifies NMI fired and passes test
 *
 * Copyright 2025 Tenstorrent Inc.
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "tb.h"
#include "nmi.h"
#include "test_completion.h"

/*
 * NMI Handler
 *
 * Called when NMI fires. This handler:
 *   1. Clears the WDT bark interrupt
 *   2. Disables the watchdog
 *   3. Exits the test with PASS
 */
void nmi_handler(void) {
    printf("NMI fired successfully!\n");

    /* Clear watchdog bark interrupt (bit 1 of INTR_STATE is wdog_timer_bark) */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR, 0x2);

    /* Disable watchdog */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x0);

    test_pass(0);

    /* Should never reach here */
    while (1) {
        __asm__ volatile("nop");
    }
}

int main(void)
{
    /* Initialize outbound filter to allow testpass mailbox access */
    sep_outbound_filter_init();

    printf("NMI Sanity Test - Non-Maskable Interrupt Verification\n");
    printf("======================================================\n\n");

    //////////////////////////////////
    // STEP 1: Register NMI handler //
    //////////////////////////////////

    printf("Registering NMI handler...\n");
    nmi_register_handler(nmi_handler);

    ////////////////////////////////////////////////
    // STEP 2: Verify trampoline is 256-byte aligned
    ////////////////////////////////////////////////

    uint32_t nmi_addr = nmi_get_vector_addr();
    printf("NMI trampoline at: 0x%08x\n", nmi_addr);

    if (nmi_addr & 0xFF) {
        printf("ERROR: NMI trampoline is not 256-byte aligned!\n");
        return 1;
    }
    printf("NMI trampoline alignment verified OK\n");

    ////////////////////////////////////////////////
    // STEP 3: Verify default SEP_NMI_VEC value
    ////////////////////////////////////////////////

    uint32_t nmi_vec_default = nmi_read_vector_reg();
    printf("SEP_NMI_VEC default: 0x%08x\n", nmi_vec_default);

    if (nmi_vec_default != 0u) {
        printf("ERROR: SEP_NMI_VEC default mismatch! Expected 0x%08x\n",
               0u);
        return 1;
    }
    printf("SEP_NMI_VEC default value verified OK\n");

    ////////////////////////////////////////////////
    // STEP 4: Set NMI vector via register
    ////////////////////////////////////////////////

    printf("Setting NMI vector via register to 0x%08x...\n", nmi_addr);
    nmi_set_vector_reg();

    /* Verify it was written correctly */
    uint32_t nmi_vec_readback = nmi_read_vector_reg();
    if (nmi_vec_readback != nmi_addr) {
        printf("ERROR: SEP_NMI_VEC write failed! Expected 0x%08x, got 0x%08x\n",
               nmi_addr, nmi_vec_readback);
        return 1;
    }
    printf("NMI vector set OK\n");

    ////////////////////////////////////////////////
    // STEP 5: Lock NMI vector register
    ////////////////////////////////////////////////

    printf("Locking SEP_NMI_VEC register...\n");
    nmi_lock_vector_reg();

    ////////////////////////////////////////////////
    // STEP 6: Verify lock is set
    ////////////////////////////////////////////////

    uint32_t lock_val = nmi_read_lock_reg();
    if (lock_val != 0x1) {
        printf("ERROR: SEP_NMI_VEC_LOCK not set! Got 0x%08x\n", lock_val);
        return 1;
    }
    printf("SEP_NMI_VEC lock verified OK\n");

    ////////////////////////////////////////////////
    // STEP 7: Test that lock prevents writes
    ////////////////////////////////////////////////

    uint32_t test_val = 0xDEADBEE0;
    printf("Testing lock - writing 0x%08x to SEP_NMI_VEC...\n", test_val);
    WRITE_REG(OCH_SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_BASE_ADDR, test_val);

    /* Verify register still has the correct NMI address */
    uint32_t locked_readback = nmi_read_vector_reg();
    printf("SEP_NMI_VEC after locked write: 0x%08x\n", locked_readback);

    if (locked_readback != nmi_addr) {
        printf("ERROR: SEP_NMI_VEC changed despite lock! Expected 0x%08x, got 0x%08x\n",
               nmi_addr, locked_readback);
        return 1;
    }
    printf("SEP_NMI_VEC lock protection verified OK\n\n");

    ////////////////////////////////////////////////
    // STEP 8: Trigger NMI using WDT bark
    ////////////////////////////////////////////////

    printf("Setting up WDT to trigger NMI...\n");

    /* Clear WDT count */
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0);

    /* Set bark threshold low for quick trigger, bite high to prevent reset */
    uint32_t bark_threshold = 100;
    uint32_t bite_threshold = 10000;

    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, bark_threshold);
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, bite_threshold);

    printf("WDOG_BARK_THOLD = %u\n", bark_threshold);
    printf("WDOG_BITE_THOLD = %u\n", bite_threshold);

    /* Enable watchdog */
    printf("Enabling watchdog to trigger NMI...\n");
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0x1);

    ////////////////////////////////////////////////
    // STEP 9: Wait for NMI
    ////////////////////////////////////////////////

    printf("Waiting for WDT bark to trigger NMI...\n\n");

    /* Spin forever - NMI will interrupt and exit */
    while (1) {
        __asm__ volatile("wfi");
    }

    /* Should never reach here */
    printf("FAIL: NMI was not triggered!\n");
    return 1;
}
