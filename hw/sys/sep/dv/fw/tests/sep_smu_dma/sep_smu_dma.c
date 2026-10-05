/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smu_dma - SMU-level SEP DMA register sanity test.
 *
 * Programs the secure DMA range, source, destination, size and control
 * registers and checks that each reads back.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h"

static int rw_check32(uint32_t addr, uint32_t value) {
    WRITE_REG(addr, value);
    return (READ_REG(addr) == value) ? 0 : -1;
}

static int run_dma_reg_sequence(void) {
    if (rw_check32(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_BASE_ADDR, 0xC0000000u) != 0)
        return -1;
    if (rw_check32(SEP_TOP_SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_BASE_ADDR, 0xC00FFFFFu) != 0)
        return -2;
    if (rw_check32(SEP_TOP_SECURE_DMA_RANGE_VALID_BASE_ADDR, 0x1u) != 0) return -3;

    if (rw_check32(SEP_TOP_SECURE_DMA_SRC_ADDR_LO_BASE_ADDR, SEP_TOP_SEP_SRAM_BASE_ADDR) != 0)
        return -4;
    if (rw_check32(SEP_TOP_SECURE_DMA_DST_ADDR_LO_BASE_ADDR,
                   SEP_TOP_SEP_SRAM_BASE_ADDR + 0x1000u) != 0)
        return -5;
    if (rw_check32(SEP_TOP_SECURE_DMA_TOTAL_DATA_SIZE_BASE_ADDR, 0x100u) != 0) return -6;

    /* Control stays idle: this test must not start a real transfer. */
    if (rw_check32(SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR, 0x0u) != 0) return -7;
    return 0;
}

__attribute__((used, noinline, noreturn)) void smu_sep_dma_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn)) void smu_sep_dma_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    sep_outbound_filter_init();
    if (run_dma_reg_sequence() == 0) {
        smu_sep_dma_pass_loop();
    } else {
        smu_sep_dma_fail_loop();
    }
}
