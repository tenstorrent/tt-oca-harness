/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_ext_irq - SMU wrapper interrupt pin 0 reaches the SEP PIC.
 *
 * Arms only the PIC source the wrapper pin maps to. A pulse while the source is
 * disabled must not trap; an enabled pulse is claimed as that source and does
 * not fire again once the gateway is cleared.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_smc_bringup.h"
#include "sep_pic.h"
#include "sep_smu_ext_irq_protocol.h"

static volatile int g_status;
static volatile uint32_t g_isr_count;
static volatile uint32_t g_claimid;

static inline uint32_t read_claimid(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, 0xFC8" : "=r"(meihap));
    return (meihap >> 2) & 0xFFu;
}

static inline void wait_mcycle(uint32_t n) {
    uint32_t start;
    uint32_t now;
    __asm__ volatile("csrr %0, mcycle" : "=r"(start));
    do {
        __asm__ volatile("csrr %0, mcycle" : "=r"(now));
    } while ((uint32_t)(now - start) < n);
}

__attribute__((interrupt("machine"))) void sep_smu_ext_irq_isr(void) {
    g_claimid = read_claimid();
    g_isr_count += 1u;
    /* The edge stays pending until main clears the gateway, so return with
     * interrupts disabled to keep the ISR from re-entering first. */
    __asm__ volatile("csrc mstatus, %0" ::"r"(1u << 7));
}

__attribute__((used, noinline)) void ext_irq_disabled_armed(void) {
    uint32_t start;
    uint32_t now;
    __asm__ volatile("csrr %0, mcycle" : "=r"(start));
    do {
        __asm__ volatile("csrr %0, mcycle" : "=r"(now));
    } while ((uint32_t)(now - start) < EXT_IRQ_DISABLED_MCYCLE);
}

/* Bounded so a pin that lands on a source nobody armed fails with a number
 * instead of hanging. Returns 0 when the ISR ran, -1 on expiry. */
__attribute__((used, noinline)) int ext_irq_armed(void) {
    uint32_t start;
    uint32_t now;
    __asm__ volatile("csrr %0, mcycle" : "=r"(start));
    while (g_isr_count == 0u) {
        __asm__ volatile("csrr %0, mcycle" : "=r"(now));
        if ((uint32_t)(now - start) >= EXT_IRQ_ISR_WAIT_MCYCLE) {
            return -1;
        }
    }
    return 0;
}

/* Whichever source is pending, or 0xFF if none. Names the source the pin
 * actually reached when SEP_NUM_INTERNAL_IRQS has drifted from the RTL. */
static uint32_t first_pending_source(void) {
    for (uint32_t src = 1u; src <= SEP_PIC_TOTAL_SOURCES; src++) {
        if (pic_source_pending(src) != 0u) {
            return src;
        }
    }
    return 0xFFu;
}

__attribute__((used, noinline, noreturn)) void sep_smu_ext_irq_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void sep_smu_ext_irq_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

static int wr_rd32(uint32_t addr, uint32_t expect) {
    WRITE_REG(addr, expect);
    if (READ_REG(addr) != expect) {
        return -1;
    }
    return 0;
}

static int arm_pic_disabled(void) {
    uint32_t src = EXT_IRQ_PIC_SOURCE;
    uint32_t meipl_addr = _pic_meipl_addr(src);
    uint32_t gw_addr = _pic_meigwctrl_addr(src);
    uint32_t meie_addr = _pic_meie_addr(src);

    pic_register_handler(src, sep_smu_ext_irq_isr);
    if (wr_rd32(meipl_addr, EXT_IRQ_MEIPL) != 0) {
        return -1;
    }
    if (wr_rd32(gw_addr, EXT_IRQ_MEIGWCTRL) != 0) {
        return -2;
    }
    pic_enable_interrupts();
    if (wr_rd32(meie_addr, 0u) != 0) {
        return -3;
    }
    if (pic_read_priority(src) != EXT_IRQ_MEIPL) {
        return -4;
    }
    if ((pic_read_gateway(src) & 0x3u) != EXT_IRQ_MEIGWCTRL) {
        return -5;
    }
    if (pic_read_source_enable(src) != 0u) {
        return -6;
    }
    return 0;
}

static int run_ext_irq(void) {
    uint32_t src = EXT_IRQ_PIC_SOURCE;
    uint32_t meie_addr = _pic_meie_addr(src);
    uint32_t start_count;

    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)EXT_IRQ_SMC_ENTRY, EXT_IRQ_SMC_IMAGE_FIRST_WORD,
                                  EXT_IRQ_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_S0_FAIL);
        return -11;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_BRINGUP_OK);

    g_isr_count = 0u;
    g_claimid = 0xFFFFFFFFu;
    if (arm_pic_disabled() != 0) {
        return -12;
    }

    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_DISABLED_ARMED);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), g_isr_count);
    ext_irq_disabled_armed();
    if (g_isr_count != 0u) {
        return -13;
    }

    pic_clear_gateway(src);
    if (pic_source_pending(src) != 0u) {
        return -14;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_DISABLED_CLEAN);
    wait_mcycle(EXT_IRQ_DISABLED_MCYCLE);
    if ((g_isr_count != 0u) || (pic_source_pending(src) != 0u)) {
        return -15;
    }

    if (wr_rd32(meie_addr, 1u) != 0) {
        return -16;
    }
    if (pic_read_source_enable(src) != 1u) {
        return -17;
    }
    if (pic_source_pending(src) != 0u) {
        return -18;
    }

    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_ARMED);
    if (ext_irq_armed() != 0) {
        /* The pin fired somewhere else: SEP_NUM_INTERNAL_IRQS no longer
         * matches sep_pkg::NUM_INTERNAL_IRQS. Publish the source that did go
         * pending so the correct constant is readable from the run. */
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(9), first_pending_source());
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3),
                              EXT_IRQ_WRONG_SOURCE | (first_pending_source() & 0xFFu));
        return -23;
    }
    if (g_isr_count != 1u) {
        return -19;
    }
    if (g_claimid != src) {
        return -20;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(9), g_claimid);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), g_isr_count);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_ISR_SEEN);

    wait_mcycle(EXT_IRQ_POST_ISR_MCYCLE);
    pic_clear_gateway(src);
    if (pic_source_pending(src) != 0u) {
        return -21;
    }
    pic_enable_interrupts();
    start_count = g_isr_count;
    wait_mcycle(EXT_IRQ_DISABLED_MCYCLE);
    if ((g_isr_count != start_count) || (g_isr_count != 1u)) {
        return -22;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), EXT_IRQ_CLEARED);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), g_isr_count);
    return 0;
}

int main(void) {
    sep_outbound_filter_init();
    g_status = run_ext_irq();
    if (g_status == 0) {
        sep_smu_ext_irq_pass_loop();
    }
    sep_smu_ext_irq_fail_loop();
}
