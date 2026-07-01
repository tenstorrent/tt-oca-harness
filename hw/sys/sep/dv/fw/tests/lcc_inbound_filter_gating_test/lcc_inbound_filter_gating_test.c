/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "sep.h"

#define PROD_LC_STATE_DIFF_ENCODED 0xE1u

static inline void mmio_write32(uint32_t addr, uint32_t val)
{
    *(volatile uint32_t *)(uintptr_t)addr = val;
}

static inline void mmio_fence(void)
{
    __asm__ volatile("fence" ::: "memory");
}

static void busy_wait(unsigned int cycles)
{
    for (volatile unsigned int i = 0; i < cycles; i++) {
        __asm__ volatile("nop");
    }
}

int main(void)
{
    // Move TEST_DEV -> PROD using the real CPU/MMIO path. PROD has sep_debug=0
    // with the default DIS vectors, so inbound external AXI should remain gated.
    mmio_write32(OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR, PROD_LC_STATE_DIFF_ENCODED);
    mmio_fence();

    // Give the UVM side a stable window to observe sep_debug=0 and prove that
    // external inbound traffic is blocked before debug is enabled.
    busy_wait(2000);

    // Real firmware path to enable PROD_DBG_1. DEMOTE_1 implies DEMOTE_2 in the
    // LCC encoding, so assert DEMOTE_2 first and then grant chiplet-owner debug.
    mmio_write32(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_2_BASE_ADDR, 1u);
    mmio_fence();
    mmio_write32(OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_DEMOTE_1_BASE_ADDR, 1u);
    mmio_fence();

    while (1) {
        __asm__ volatile("wfi");
    }
}
