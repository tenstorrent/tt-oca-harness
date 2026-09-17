/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_debug_bus - retire-trace producer for smu_sep_debug_bus_test.
 *
 * Frontdoor-brings the dedicated SMC DFD-arm image, publishes SEP_WAIT
 * through alias scratch3, parks at debug_bus_wait_for_go polling GO, then
 * executes the exact self-loop marker so the SMC CLA can snapshot PC[15:0].
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_smc_bringup.h"
#include "sep_smu_debug_bus_protocol.h"

__attribute__((used, noinline)) void debug_bus_wait_for_go(void) {
    while (READ_REG(DEBUG_BUS_GO_ALIAS) != DEBUG_BUS_GO) {
        __asm__ volatile("" ::: "memory");
    }
}

__attribute__((naked, used, noinline, noreturn)) void debug_bus_marker(void) {
    __asm__ volatile("jal x0, debug_bus_marker");
}

__attribute__((used, noinline, noreturn)) void sep_smu_debug_bus_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

static void (*const keep_fail)(void) = sep_smu_debug_bus_fail_loop;

static int run_debug_bus(void) {
    uint32_t seen;

    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)DEBUG_BUS_SMC_ENTRY, DEBUG_BUS_SMC_IMAGE_FIRST_WORD,
                                  DEBUG_BUS_HANDSHAKE_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), DEBUG_BUS_S0_FAIL);
        return -11;
    }

    /* Card S3: SMC must clear scratch2/3 first. Wait for PH_CLEARED so a
     * late SMC start cannot wipe SEP_WAIT. */
    if (sep_smc_scratch_wait(DEBUG_BUS_PHASE_ALIAS, DEBUG_BUS_PH_CLEARED,
                             DEBUG_BUS_HANDSHAKE_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), DEBUG_BUS_S0_FAIL);
        return -15;
    }

    sep_smc_scratch_write(DEBUG_BUS_WAIT_ALIAS, DEBUG_BUS_SEP_WAIT);
    seen = READ_REG(DEBUG_BUS_WAIT_ALIAS);
    if (seen != DEBUG_BUS_SEP_WAIT) {
        return -12;
    }

    debug_bus_wait_for_go();

    sep_smc_scratch_write(DEBUG_BUS_WAIT_ALIAS, DEBUG_BUS_GO_SEEN);
    seen = READ_REG(DEBUG_BUS_WAIT_ALIAS);
    if (seen != DEBUG_BUS_GO_SEEN) {
        return -13;
    }

    (void)keep_fail;
    debug_bus_marker();
    return -14;
}

int main(void) {
    sep_outbound_filter_init();
    if (run_debug_bus() != 0) {
        sep_smu_debug_bus_fail_loop();
    }
    sep_smu_debug_bus_fail_loop();
}
