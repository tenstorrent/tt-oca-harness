/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_otbn - SMU-level SEP OTBN CSR programming smoke test.
 *
 * Exercises benign OTBN CSR writes only; no IMEM/DMEM load or EXECUTE.
 *
 * OTBN lives at OCH_SEP_TOP_OTBN_BASE_ADDR in the SEP's own peripheral region,
 * so these accesses stay on the SEP-internal fabric and never reach the
 * outbound filter. INTR_ENABLE.done is sw=rw storage, so it is read back after
 * the write burst: a write dropped or absorbed by a default slave then returns
 * the wrong value and the image parks in the fail loop.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

/* Written to INTR_ENABLE and required back from it; bit 0 is the only field. */
#define OTBN_INTR_ENABLE_PROBE 0x1u

static volatile int g_otbn_status;

static int run_otbn_programming_sequence(void) {
    WRITE_REG(OCH_SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, OTBN_INTR_ENABLE_PROBE);
    WRITE_REG(OCH_SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_OTBN_ERR_BITS_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_OTBN_INSN_CNT_BASE_ADDR, 0xFFFFFFFFu);
    WRITE_REG(OCH_SEP_TOP_OTBN_LOAD_CHECKSUM_BASE_ADDR, 0x0u);

    if (READ_REG(OCH_SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR) != OTBN_INTR_ENABLE_PROBE) {
        g_otbn_status = 1;
    }

    return g_otbn_status;
}

__attribute__((used, noinline, noreturn)) void smu_sep_otbn_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_otbn_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    sep_outbound_filter_init();
    if (run_otbn_programming_sequence() == 0) {
        smu_sep_otbn_pass_loop();
    } else {
        smu_sep_otbn_fail_loop();
    }
}
