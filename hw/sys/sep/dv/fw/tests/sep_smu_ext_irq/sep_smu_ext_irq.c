/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_ext_irq - SEP_SMU_008 wrapper pin bit0 through EL2 PIC.
 *
 * Frontdoor-brings SMC, arms exactly PIC source 39 (pin bit0 with
 * NUM_INTERNAL_IRQS=38), proves a disabled pulse does not trap, then an
 * enabled pulse claims 39, waits 32 mcycle, MEIGWCLR, no-refire, pass_loop.
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
    /* Edge pending stays until MEIGWCLR. Clear MPIE so mret leaves MIE=0 and
     * main can run the 32-mcycle delay + MEIGWCLR (card: ISR does not clear). */
    __asm__ volatile("csrc mstatus, %0" ::"r"(1u << 7));
}

__attribute__((used, noinline)) void ext_irq_disabled_armed(void) {
    uint32_t start;
    uint32_t now;
    __asm__ volatile("csrr %0, mcycle" : "=r"(start));
    do {
        __asm__ volatile("csrr %0, mcycle" : "=r"(now));
    } while ((uint32_t)(now - start) < IRQ008_DISABLED_MCYCLE);
}

__attribute__((used, noinline)) void ext_irq_armed(void) {
    while (g_isr_count == 0u) {
        __asm__ volatile("" ::: "memory");
    }
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

static void (*const keep_fail)(void) = sep_smu_ext_irq_fail_loop;

static int wr_rd32(uint32_t addr, uint32_t expect) {
    WRITE_REG(addr, expect);
    if (READ_REG(addr) != expect) {
        return -1;
    }
    return 0;
}

static int arm_pic_disabled(void) {
    uint32_t src = IRQ008_PIC_SOURCE;
    uint32_t meipl_addr = SEP_PIC_MEIPL_0 + (src - 1u) * 4u;
    uint32_t gw_addr = SEP_PIC_MEIGWCTRL_0 + (src - 1u) * 4u;
    uint32_t meie_addr = SEP_PIC_MEIE_0 + (src - 1u) * 4u;

    pic_register_handler(src, sep_smu_ext_irq_isr);
    if (wr_rd32(meipl_addr, IRQ008_MEIPL) != 0) {
        return -1;
    }
    if (wr_rd32(gw_addr, IRQ008_MEIGWCTRL) != 0) {
        return -2;
    }
    pic_enable_interrupts();
    if (wr_rd32(meie_addr, 0u) != 0) {
        return -3;
    }
    if (pic_read_priority(src) != IRQ008_MEIPL) {
        return -4;
    }
    if ((pic_read_gateway(src) & 0x3u) != IRQ008_MEIGWCTRL) {
        return -5;
    }
    if (pic_read_source_enable(src) != 0u) {
        return -6;
    }
    return 0;
}

static int run_ext_irq(void) {
    uint32_t src = IRQ008_PIC_SOURCE;
    uint32_t meie_addr = SEP_PIC_MEIE_0 + (src - 1u) * 4u;
    uint32_t start_count;

    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)IRQ008_SMC_ENTRY, IRQ008_SMC_IMAGE_FIRST_WORD,
                                  IRQ008_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_S0_FAIL);
        return -11;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_BRINGUP_OK);

    g_isr_count = 0u;
    g_claimid = 0xFFFFFFFFu;
    if (arm_pic_disabled() != 0) {
        return -12;
    }

    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_DISABLED_ARMED);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), g_isr_count);
    ext_irq_disabled_armed();
    if (g_isr_count != 0u) {
        return -13;
    }

    pic_clear_gateway(src);
    if (pic_source_pending(src) != 0u) {
        return -14;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_DISABLED_CLEAN);
    wait_mcycle(IRQ008_DISABLED_MCYCLE);
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

    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_ARMED);
    ext_irq_armed();
    if (g_isr_count != 1u) {
        return -19;
    }
    if (g_claimid != src) {
        return -20;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(9), g_claimid);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), g_isr_count);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_ISR_SEEN);

    wait_mcycle(IRQ008_POST_ISR_MCYCLE);
    pic_clear_gateway(src);
    if (pic_source_pending(src) != 0u) {
        return -21;
    }
    pic_enable_interrupts();
    start_count = g_isr_count;
    wait_mcycle(IRQ008_DISABLED_MCYCLE);
    if ((g_isr_count != start_count) || (g_isr_count != 1u)) {
        return -22;
    }
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(3), IRQ008_CLEARED);
    sep_smc_scratch_write(SEP_SMC_SCRATCH_ALIAS(10), g_isr_count);
    (void)keep_fail;
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
