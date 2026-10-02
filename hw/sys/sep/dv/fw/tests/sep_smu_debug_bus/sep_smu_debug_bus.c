/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_debug_bus - SEP retire-trace producer for the SMU debug-bus test.
 *
 * Brings up the dedicated SMC debug-arm image, publishes a wait marker in
 * shared scratch, parks in debug_bus_wait_for_go until the SMC sends GO, then
 * executes the self-loop marker whose PC the SMC CLA matches.
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

static int run_debug_bus(void) {
    uint32_t seen;

    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)DEBUG_BUS_SMC_ENTRY, DEBUG_BUS_SMC_IMAGE_FIRST_WORD,
                                  DEBUG_BUS_HANDSHAKE_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), DEBUG_BUS_S0_FAIL);
        return -11;
    }

    /* The SMC clears the shared scratch when it starts; wait for that so a
     * late SMC start cannot wipe the wait marker. */
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

    debug_bus_marker();
}

int main(void) {
    sep_outbound_filter_init();
    if (run_debug_bus() != 0) {
        sep_smu_debug_bus_fail_loop();
    }
    sep_smu_debug_bus_fail_loop();
}
