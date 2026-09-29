/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OTBN Interrupt to PLIC Test (INT-002, P1)
 *
 * Verifies OTBN done interrupt routing from INTR_STATE through to the
 * VeeR EL2 PIC (Programmable Interrupt Controller).
 *
 * Test steps:
 * 1. Wait for OTBN IDLE (initial secure wipe)
 * 2. Register OTBN interrupt handler in PIC vector table
 * 3. Enable OTBN interrupt in PIC and globally
 * 4. Enable OTBN done interrupt (INTR_ENABLE.done = 1)
 * 5. Issue SEC_WIPE_DMEM command
 * 6. Verify ISR fires (via volatile flag) OR poll INTR_STATE.done
 * 7. Clear interrupt in ISR / via W1C
 * 8. Verify ISR exited correctly
 *
 * RTL interrupt routing path:
 *       otbn.intr_done_o → sep_crypto_otbn_wrapper.intr_done_o
 *       → sep_crypto.intr_otbn_done_o → sep.intr_otbn_done
 *       → sep_internal_interrupts[29] → sep_interrupts[29]
 *       → VeeR EL2 extintsrc_req[30] → PIC source 30
 *
 * Note: PIC source = sep_internal_interrupts index + 1 (extintsrc_req is 1-based;
 * bit 0 is the tied no-interrupt source). OTBN done is internal index 29 -> PIC
 * source 30 (hw/sys/sep/rtl/sep.sv). This test
 * REQUIRES the ISR to fire (no INTR_STATE poll fallback):
 * polling INTR_STATE only proves the IP status register, not CPU delivery.
 */

#include <stdint.h>
#include <stdio.h>

#include "och_sep_common.h"
#include "sep.h"
#include "interrupt.h"
#include "sep_outbound_filter.h"
#include "test_completion.h"

/* OTBN constants */
#define OTBN_STATUS_IDLE 0x00u
#define OTBN_CMD_SEC_WIPE_DMEM 0xC3u
#define OTBN_CMD_SEC_WIPE_IMEM 0x1Eu

#define OTBN_IDLE_TIMEOUT 20000

/* OTBN PIC source ID — sep_internal_interrupts[29] -> PIC source 30 (idx + 1) */
#define OTBN_PIC_SOURCE_ID 30u

/* Volatile flag set by ISR */
static volatile uint32_t g_otbn_isr_fired = 0;
static volatile uint32_t g_otbn_isr_count = 0;
static volatile uint32_t g_otbn_claimid = 0xFFFFFFFFu;

/* Forward declarations */
static int otbn_wait_for_idle(void);

/* Read the VeeR EL2 meihap CSR (0xFC8); claim id = (meihap >> 2) & 0xFF. */
static inline uint32_t read_claimid(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, 0xFC8" : "=r"(meihap));
    return (meihap >> 2) & 0xFFu;
}

/*
 * OTBN done interrupt service routine.
 * Declared with interrupt attribute for VeeR EL2 PIC.
 */
__attribute__((interrupt("machine"))) void otbn_done_isr(void) {
    g_otbn_isr_fired = 1;
    g_otbn_isr_count++;
    g_otbn_claimid = read_claimid();

    /* Clear OTBN INTR_STATE.done via W1C */
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0x1u);
}

static int otbn_wait_for_idle(void) {
    for (int t = OTBN_IDLE_TIMEOUT; t > 0; --t) {
        uint32_t status = READ_REG(SEP_TOP_OTBN_STATUS_BASE_ADDR);
        if (status == OTBN_STATUS_IDLE) return 0;
        for (volatile int i = 0; i < 256; ++i)
            ;
    }
    printf("ERROR: Timed out waiting for OTBN IDLE\n");
    return -1;
}

static void fail_and_halt(int code, const char *msg) {
    printf("FAIL: %s\n", msg);
    test_fail(code);
    while (1) {
        __asm__("wfi");
    }
}

int main(void) {
    int errors = 0;
    sep_outbound_filter_init();

    printf("\n");
    printf("******************************************\n");
    printf("*  OTBN Interrupt to PLIC Test (INT-002) *\n");
    printf("******************************************\n\n");

    /* ----------------------------------------------------------------
     * Step 1: Wait for OTBN IDLE
     * ---------------------------------------------------------------- */
    printf("[STEP 1/8] Waiting for OTBN IDLE...\n");
    if (otbn_wait_for_idle() != 0) {
        fail_and_halt(1, "OTBN did not reach IDLE");
    }
    printf("[STEP 1/8] OTBN is IDLE\n");

    /* ----------------------------------------------------------------
     * Step 2: Register OTBN interrupt handler
     * ---------------------------------------------------------------- */
    printf("[STEP 2/8] Registering OTBN interrupt handler (source_id=%u)...\n", OTBN_PIC_SOURCE_ID);
    pic_register_handler(OTBN_PIC_SOURCE_ID, otbn_done_isr);
    printf("[STEP 2/8] Handler registered\n");

    /* ----------------------------------------------------------------
     * Step 3: Enable OTBN interrupt in PIC
     * ---------------------------------------------------------------- */
    printf("[STEP 3/8] Configuring PIC for OTBN interrupt...\n");
    pic_set_gateway(OTBN_PIC_SOURCE_ID, 0, 0); /* level-triggered, active-high */
    pic_set_priority(OTBN_PIC_SOURCE_ID, 1);
    pic_enable_source(OTBN_PIC_SOURCE_ID);
    pic_enable_interrupts();
    printf("[STEP 3/8] PIC configured and interrupts enabled\n");

    /* ----------------------------------------------------------------
     * Step 4: Enable OTBN done interrupt
     * ---------------------------------------------------------------- */
    printf("[STEP 4/8] Enabling OTBN done interrupt (INTR_ENABLE=1)...\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, 0x1u);
    /* Clear any pending interrupt */
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xFFFFFFFFu);
    g_otbn_isr_fired = 0;
    g_otbn_isr_count = 0;
    printf("[STEP 4/8] OTBN done interrupt enabled\n");

    /* ----------------------------------------------------------------
     * Step 5: Issue SEC_WIPE_DMEM
     * ---------------------------------------------------------------- */
    printf("[STEP 5/8] Issuing SEC_WIPE_DMEM command...\n");
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_SEC_WIPE_DMEM);

    /* ----------------------------------------------------------------
     * Step 6: Require the ISR (CPU trap). This is the actual PIC->CPU
     * delivery check - there is NO INTR_STATE poll fallback, because polling
     * the IP status register proves nothing about delivery to the CPU.
     * ---------------------------------------------------------------- */
    printf("[STEP 6/8] Waiting for CPU trap / ISR...\n");
    for (volatile int i = 0; i < 20000 && !g_otbn_isr_fired; ++i)
        ;

    if (g_otbn_isr_fired) {
        printf("[STEP 6/8] ISR fired (count=%u) at PIC claim id %u — delivery confirmed\n",
               g_otbn_isr_count, g_otbn_claimid);
    } else {
        printf("[STEP 6/8] ISR did NOT fire — sep_interrupts[29] -> PIC -> CPU "
               "delivery BROKEN\n");
        errors++;
    }

    /* ----------------------------------------------------------------
     * Step 7: Clear interrupt
     * ---------------------------------------------------------------- */
    printf("[STEP 7/8] Clearing OTBN done interrupt...\n");
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0x1u); /* W1C */
    uint32_t intr_after_clear = READ_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR);
    if (intr_after_clear & 0x1u) {
        printf("WARNING: INTR_STATE.done still set after W1C (=0x%08x)\n", intr_after_clear);
        errors++;
    } else {
        printf("[STEP 7/8] INTR_STATE.done cleared\n");
    }

    /* ----------------------------------------------------------------
     * Step 8: Verify final state
     * ---------------------------------------------------------------- */
    printf("[STEP 8/8] Verifying final state...\n");
    if (otbn_wait_for_idle() != 0) {
        fail_and_halt(8, "OTBN did not return to IDLE");
    }

    /* === Second wipe (SEC_WIPE_IMEM) for additional coverage === */
    printf("\n--- Additional coverage: SEC_WIPE_IMEM ---\n");
    g_otbn_isr_fired = 0;
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_SEC_WIPE_IMEM);

    for (volatile int i = 0; i < 10000; ++i)
        ;

    if (g_otbn_isr_fired) {
        printf("SEC_WIPE_IMEM: ISR fired (count=%u)\n", g_otbn_isr_count);
    } else {
        printf("ERROR: SEC_WIPE_IMEM ISR did not fire — PIC->CPU delivery BROKEN\n");
        errors++;
    }
    WRITE_REG(SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0x1u);

    if (otbn_wait_for_idle() != 0) {
        fail_and_halt(9, "OTBN did not return to IDLE after IMEM wipe");
    }

    /* === Report === */
    printf("\n========================================\n");
    printf("INT-002: OTBN Interrupt to PLIC Test\n");
    printf("  ISR fired:   %s (count=%u)\n", g_otbn_isr_count > 0 ? "YES" : "NO", g_otbn_isr_count);
    printf("  Claim id:    %u (expected 30 for sep_internal_interrupts[29])\n", g_otbn_claimid);
    printf("  Errors:      %d\n", errors);
    printf("========================================\n");

    if (errors == 0) {
        printf("PASS: OTBN PLIC test completed\n");
        test_pass(0);
    } else {
        printf("FAIL: %d errors\n", errors);
        test_fail(1);
    }

    while (1) {
        __asm__("wfi");
    }
}
