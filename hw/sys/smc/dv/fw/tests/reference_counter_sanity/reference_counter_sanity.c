/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief SMC Reference Counter Test
 *
 * Verifies that the SMC CPU reference counter is free-running, and that a
 * software write reloads it, after which it keeps counting.
 */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

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
    uint32_t start_refclk_count = read_reg(SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);

    for (int i = 0; i < POLL_MAX; i++) {
        uint32_t refclk_count = read_reg(SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);
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
        uint32_t refclk_count = read_reg(SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR);
        *last = refclk_count;
        if ((refclk_count - target) < REF_COUNT_WR_MARGIN) {
            return 0;
        }
    }
    return -1;
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    simputs("SMC Reference Counter Test\n");
    simputs("====================================\n\n");

    if (wait_refclk_advance() != 0) {
        simputs("\n*** SMC Reference Counter Test FAILED (counter stuck) ***\n");
        test_fail(hartid);
    }

    write_reg(SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR, REF_COUNT_WR_VALUE);
    uint32_t readback;
    if (wait_counter_update(REF_COUNT_WR_VALUE, &readback) != 0) {
        simputshex32("\n*** SMC Reference Counter Test FAILED (write not applied), wrote ",
                     REF_COUNT_WR_VALUE);
        simputshex32("read ", readback);
        test_fail(hartid);
    }

    if (wait_refclk_advance() != 0) {
        simputs("\n*** SMC Reference Counter Test FAILED (stuck after write) ***\n");
        test_fail(hartid);
    }

    simputs("\n*** SMC Reference Counter Test PASSED ***\n");
    test_pass(hartid);

    return 0;
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    }

    while (true) {
        __asm__("wfi");
    }
    return 0;
}
