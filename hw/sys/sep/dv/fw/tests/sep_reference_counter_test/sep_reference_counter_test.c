/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * SEP Reference Counter Test
 *
 * This test verifies REFERENCE_COUNTER (sep_cpu_ctrl) is a free-running
 * reference-clock counter, using the refclk poll from hw/sys/smc/dv/fw/tests/avsbus_sanity.
 *
 * Test flow:
 * 1. Sample the counter and poll until it counts up (fail if it never advances)
 * 2. Write the counter CSR and confirm the counter reloads to the written
 *    value (wr_swacc update path)
 * 3. Confirm the counter keeps counting from the written value
 *
 ******************************************************************************/

#include <stdio.h>
#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"
#include "test_completion.h"
#include "sep_outbound_filter.h"

// Reference-clock cycles to wait for the counter to advance.
#define REFCLK_CYCLES 10
// Upper bound on read attempts before declaring the counter stuck.
#define POLL_MAX 100000
// Distinctive value written to the counter, far above its free-running value.
#define REF_COUNT_WR_VALUE 0xC0FFEE00u
// Allowed counter advance between the CSR write and the readback (CDC
// crossing latency plus firmware bus access time, in refclk ticks).
#define REF_COUNT_WR_MARGIN 0x10000u

// Poll the counter until it counts up by REFCLK_CYCLES; returns 0 on success,
// -1 if it never advanced (counter stuck).
static int wait_refclk_advance(void) {
    uint32_t start_refclk_count = READ_REG(SEP_TOP_SEP_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);

    for (int i = 0; i < POLL_MAX; i++) {
        uint32_t refclk_count = READ_REG(SEP_TOP_SEP_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);
        if (refclk_count >= start_refclk_count + REFCLK_CYCLES) {
            return 0;
        }
    }
    return -1;
}

// Poll until the counter reflects the written value (the update takes several
// refclk cycles to cross into the counter domain and sync back); returns 0 on
// success, -1 on timeout with the last readback in *last.
static int wait_counter_update(uint32_t target, uint32_t *last) {
    for (int i = 0; i < POLL_MAX; i++) {
        uint32_t refclk_count = READ_REG(SEP_TOP_SEP_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);
        *last = refclk_count;
        if ((refclk_count - target) < REF_COUNT_WR_MARGIN) {
            return 0;
        }
    }
    return -1;
}

int main(void) {
    sep_outbound_filter_init();

    printf("SEP Reference Counter Test\n");
    printf("====================================\n\n");

    // Step 1: read refclk counter and wait until it counts up
    if (wait_refclk_advance() != 0) {
        printf("\n*** SEP Reference Counter Test FAILED (counter stuck) ***\n");
        test_fail(0);
        while (1) __asm__ volatile("wfi");
    }

    // Step 2: write a distinctive value to the counter CSR and confirm the
    // counter reloaded to it (wr_swacc path); readback must land within
    // REF_COUNT_WR_MARGIN above the written value
    WRITE_REG(SEP_TOP_SEP_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR, REF_COUNT_WR_VALUE);
    uint32_t readback;
    if (wait_counter_update(REF_COUNT_WR_VALUE, &readback) != 0) {
        printf("\n*** SEP Reference Counter Test FAILED (write not applied: "
               "wrote 0x%08lx, read 0x%08lx) ***\n",
               (unsigned long)REF_COUNT_WR_VALUE, (unsigned long)readback);
        test_fail(0);
        while (1) __asm__ volatile("wfi");
    }

    // Step 3: confirm the counter keeps counting from the written value
    if (wait_refclk_advance() != 0) {
        printf("\n*** SEP Reference Counter Test FAILED (stuck after write) ***\n");
        test_fail(0);
        while (1) __asm__ volatile("wfi");
    }

    printf("\n*** SEP Reference Counter Test PASSED ***\n");
    test_pass(0);
    while (1) __asm__ volatile("wfi");
}
