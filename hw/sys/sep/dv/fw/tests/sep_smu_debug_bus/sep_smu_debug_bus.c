/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_debug_bus - SEP_SMU_017 retire-trace producer.
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
    while (READ_REG(DBG017_GO_ALIAS) != DBG017_GO) {
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
    if (sep_smc_bringup_from_sram((uint32_t)DBG017_SMC_ENTRY, DBG017_SMC_IMAGE_FIRST_WORD,
                                  DBG017_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), DBG017_S0_FAIL);
        return -11;
    }

    /* Card S3: SMC must clear scratch2/3 first. Wait for PH_CLEARED so a
     * late SMC start cannot wipe SEP_WAIT. */
    if (sep_smc_scratch_wait(DBG017_PHASE_ALIAS, DBG017_PH_CLEARED, DBG017_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), DBG017_S0_FAIL);
        return -15;
    }

    sep_smc_scratch_write(DBG017_WAIT_ALIAS, DBG017_SEP_WAIT);
    seen = READ_REG(DBG017_WAIT_ALIAS);
    if (seen != DBG017_SEP_WAIT) {
        return -12;
    }

    debug_bus_wait_for_go();

    sep_smc_scratch_write(DBG017_WAIT_ALIAS, DBG017_GO_SEEN);
    seen = READ_REG(DBG017_WAIT_ALIAS);
    if (seen != DBG017_GO_SEEN) {
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
