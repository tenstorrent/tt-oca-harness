/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_wdt - SEP_SMU_005 FW-armed WDT bark NMI then sticky bite.
 *
 * Frontdoor-brings SMC, programs SEP_NMI_VEC, arms aon_timer WDOG
 * (bark=0x200, bite=0x400), handles exactly one bark NMI, publishes
 * POST_NMI_ALIVE, then stops petting so the real bite asserts.
 * Recovery is out of scope (DG-WDT-STICKY).
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_smc_bringup.h"
#include "nmi.h"
#include "aon_timer.h"
#include "sep_smu_wdt_protocol.h"

static volatile int g_wdt_status;
static volatile uint32_t g_bark_nmi_count;
static volatile uint32_t g_bark_seen;
static volatile uint32_t g_interrupted_pc;
static volatile uint32_t g_post_nmi_alive;

static int wr_rd32(uint32_t addr, uint32_t expect) {
    WRITE_REG(addr, expect);
    if (READ_REG(addr) != expect) {
        return -1;
    }
    return 0;
}

void sep_smu_wdt_nmi_handler(void) {
    uint32_t st = READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR);
    if ((st & AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) == 0u) {
        g_wdt_status = -20;
        return;
    }
    g_bark_seen = 1u;
    __asm__ volatile("csrr %0, mepc" : "=r"(g_interrupted_pc));
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);
    if ((READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR) &
         AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) != 0u) {
        g_wdt_status = -21;
        return;
    }
    g_bark_nmi_count += 1u;
}

__attribute__((used, noinline)) void smu_sep_wdt_post_nmi_alive(void) {
    g_post_nmi_alive += 1u;
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), WDT005_POST_NMI_ALIVE);
}

__attribute__((used, noinline, noreturn)) void smu_sep_wdt_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_wdt_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

static int arm_wdt_and_wait_bite(void) {
    uint32_t nmi_vec;
    uint32_t rb;

    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)WDT005_SMC_ENTRY, WDT005_SMC_IMAGE_FIRST_WORD,
                                  WDT005_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), WDT005_S0_FAIL);
        return -11;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), WDT005_BRINGUP_OK);

    if ((g_bark_nmi_count != 0u) || (g_bark_seen != 0u)) {
        return -12;
    }

    nmi_register_handler(sep_smu_wdt_nmi_handler);
    nmi_set_vector_reg();
    nmi_vec = nmi_get_vector_addr();
    rb = nmi_read_vector_reg();
    if (rb != nmi_vec) {
        return -13;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(1), rb);

    if (wr_rd32(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, 0u) != 0) {
        return -1;
    }
    if (wr_rd32(OCH_SEP_TOP_WDT_TIMER_WDOG_COUNT_BASE_ADDR, 0u) != 0) {
        return -2;
    }
    if (wr_rd32(OCH_SEP_TOP_WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR, WDT005_BARK_THOLD) != 0) {
        return -3;
    }
    if (wr_rd32(OCH_SEP_TOP_WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR, WDT005_BITE_THOLD) != 0) {
        return -4;
    }
    WRITE_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR,
              AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm);
    if ((READ_REG(OCH_SEP_TOP_WDT_TIMER_INTR_STATE_BASE_ADDR) &
         AON_TIMER__INTR_STATE__WDOG_TIMER_BARK_bm) != 0u) {
        return -5;
    }
    if (wr_rd32(OCH_SEP_TOP_WDT_TIMER_WDOG_CTRL_BASE_ADDR, AON_TIMER__WDOG_CTRL__ENABLE_bm) != 0) {
        return -6;
    }

    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), WDT005_NMI_ARMED);

    while (g_bark_nmi_count == 0u) {
        /* Spin (no WFI) so post-NMI liveness is distinguishable from halt. */
    }
    if (g_bark_nmi_count != 1u) {
        return -22;
    }
    smu_sep_wdt_post_nmi_alive();
    while (1) {
        g_post_nmi_alive += 1u;
    }
}

int main(void) {
    sep_outbound_filter_init();
    g_wdt_status = arm_wdt_and_wait_bite();
    if (g_wdt_status == 0) {
        smu_sep_wdt_pass_loop();
    }
    smu_sep_wdt_fail_loop();
}
