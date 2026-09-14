/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// PLL/clock initialization for OROM.
//
// PLL initialization flow for the ROM.
// Accesses PLL registers through SMC window (SMC_LOCAL_BASE_ADDR + offset).
//
// Platform-specific notes:
// - SMC base is read dynamically from sep_cpu_ctrl (via sep_smc_interface.h)
// - Fuse sense check uses SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS (sep_cpu_ctrl local reg)
// - OCAH does not distinguish between chiplet types; uses a single
//   PLL lock + mux path (to be refined when chiplet ID is available)

#include "pll_init.h"
#include "rom_mmio.h"
#include "errors.h"
#include "sep_smc_interface.h"
#include "sep.h"

// Fuse sense done is bit 0 of SMC_FUSE_SENSE_STATUS (SEP-local register).
#define FUSE_SENSE_DONE_MASK 0x1u

static void wait_for_smc_fuse_sense(void) {
    // Poll SMC_FUSE_SENSE_STATUS until smc_fuse_sense_done=1.
    // This is the fuse-sense completion wait used by the boot flow.
    while ((mmio_read32(OCH_SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR) &
            FUSE_SENSE_DONE_MASK) == 0u) {
        // spin
    }
}

uint16_t pll_init(bool bl0_pll_clk_strap) {
    if (!bl0_pll_clk_strap) {
        simputs("CLK_REFCLK\n");
        return (uint16_t)SMU_REF_CLK_FREQ_MHZ;
    }

    // Wait for fuse sense completion (SMC fuses initialize PLLs).
    simputs("PLL_WAIT_FUSE\n");
    wait_for_smc_fuse_sense();

    const uint32_t smc_base = sep_get_smc_base();
    simputshex32("SMC_BASE=", smc_base);

    // Read sysclk frequency: 11-bit fuse field indicates configured sysclk PLL frequency in MHz.
    // If 0 (fuses blank), fall back to REF_CLK.
    uint32_t sysclk_fuse = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SYSCLK_FREQ_MHZ_BASE_ADDR);
    uint16_t pll_freq_mhz =
        (uint16_t)((sysclk_fuse & SEP_EFUSE_MAP__SYSCLK_FREQ_MHZ__SYSCLK_FREQ_MHZ_bm) >>
                   SEP_EFUSE_MAP__SYSCLK_FREQ_MHZ__SYSCLK_FREQ_MHZ_bp);
    if (pll_freq_mhz == 0u) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_PLL_FUSES_BLANK);
        simputs("PLL_FUSES_BLANK\n");
        report_status(STATUS_TYPE_INFO, SEP_MSG_REF_CLK_SELECTED);
        return (uint16_t)SMU_REF_CLK_FREQ_MHZ;
    }

    // Poll PLL lock detect (CGM_0_STATUS.lock_detect, bit 0).
    simputs("PLL_WAIT_LOCK\n");
    const uint32_t pll_status_addr = smc_base + PLL_CGM_0_STATUS_OFFSET;
    while ((mmio_read32(pll_status_addr) & PLL_CGM_LOCK_DETECT_MASK) == 0u) {
        // spin — no timeout; the strap-controlled path avoids hangs
    }
    simputs("PLL_LOCKED\n");

    // Switch clock mux from refclk to PLL.
    // Write the mux select register to choose PLL for sysclk and peripheral clock.
    // OCAH: write mux select register via SMC window.
    const uint32_t mux_addr = smc_base + PLL_AG_MUX_SELECT_OFFSET;
    // Value 0x04040101: selects PLL for both sysclk and peripheral clock
    // and may need platform-specific tuning.
    mmio_write32(mux_addr, 0x04040101u);

    simputshex32("CLK_PLL freq=", (uint32_t)pll_freq_mhz);

    return pll_freq_mhz;
}
