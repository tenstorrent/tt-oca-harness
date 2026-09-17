/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_lc_handoff - PROD eFuse + DEMOTE_1 consumer setup.
 *
 * Frontdoor-brings the dedicated SMC PVT-arm image, waits for PVT_EN, parks
 * in a bounded blocked window, then writes LCC DEMOTE_1.demote=1
 * (no lock; W1S). Does not program SMC PVT CSRs: those
 * aliases trap on the SEP->SMC port.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_smc_bringup.h"
#include "sep_smu_lc_handoff_protocol.h"

static inline void wait_mcycle(uint32_t n) {
    uint32_t start;
    uint32_t now;
    __asm__ volatile("csrr %0, mcycle" : "=r"(start));
    do {
        __asm__ volatile("csrr %0, mcycle" : "=r"(now));
    } while ((uint32_t)(now - start) < n);
}

__attribute__((used, noinline)) void lc_handoff_blocked_window(void) {
    wait_mcycle(LC_HANDOFF_WINDOW_MCYCLE);
}

__attribute__((used, noinline)) void lc_handoff_demote_window(void) {
    wait_mcycle(LC_HANDOFF_WINDOW_MCYCLE);
}

__attribute__((used, noinline, noreturn)) void sep_smu_lc_handoff_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_lc_handoff_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

static void (*const keep_fail)(void) = sep_smu_lc_handoff_fail_loop;

static int run_lc_handoff(void) {
    uint32_t lc;
    uint32_t rb;

    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)LC_HANDOFF_SMC_ENTRY, LC_HANDOFF_SMC_IMAGE_FIRST_WORD,
                                  LC_HANDOFF_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_S0_FAIL);
        return -11;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_BRINGUP_OK);

    if (sep_smc_scratch_wait(LC_HANDOFF_PVT_EN_ALIAS, LC_HANDOFF_PVT_EN,
                             LC_HANDOFF_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_S0_FAIL);
        return -12;
    }

    lc = READ_REG(OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR) & 0xFFu;
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(9), lc);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_ARMED);
    lc_handoff_blocked_window();

    /* Demote is defined only in PROD. Fail if the image is not that state. */
    if (lc != LC_HANDOFF_LC_PROD_ENC) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_NOT_PROD_FAIL);
        return -15;
    }

    WRITE_REG(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR, LC_HANDOFF_DEMOTE_RAW);
    rb = READ_REG(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR) & 0x3u;
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), rb);
    if ((rb & 0x1u) == 0u) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_S0_FAIL);
        return -13;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_DEMOTE1);
    lc_handoff_demote_window();

    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), LC_HANDOFF_PASS);
    return 0;
}

int main(void) {
    sep_outbound_filter_init();
    if (run_lc_handoff() == 0) {
        sep_smu_lc_handoff_pass_loop();
    }
    (void)keep_fail;
    sep_smu_lc_handoff_fail_loop();
}
