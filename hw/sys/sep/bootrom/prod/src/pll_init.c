/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Clock source selection for the ROM.
//
// SEP owns no PLL. The PLL, its lock-detect status, and the sysclk/peripheral
// clock mux are SMC-owned adopter IP; this code only decides, from the
// `bl0_pll_clk` strap and the SYSCLK_FREQ_MHZ fuse, whether SEP moves off the
// 100 MHz reference clock, and leaves the switch itself to
// sep_pll_lock_and_select(). With the strap clear the ROM stays on refclk.

#include "pll_init.h"
#include "rom_mmio.h"
#include "errors.h"
#include "sep_smc_interface.h"
#include "sep.h"

uint16_t pll_init(bool bl0_pll_clk_strap) {
    if (!bl0_pll_clk_strap) {
        simputs("CLK_REFCLK\n");
        return (uint16_t)SMU_REF_CLK_FREQ_MHZ;
    }

    // Read sysclk frequency: 11-bit fuse field indicates configured sysclk PLL frequency in MHz.
    // If 0 (fuses blank), fall back to REF_CLK.
    uint32_t sysclk_fuse = mmio_read32(SEP_TOP_SEP_EFUSE_MAP_SYSCLK_FREQ_MHZ_BASE_ADDR);
    uint16_t pll_freq_mhz =
        (uint16_t)((sysclk_fuse & SEP_EFUSE_MAP__SYSCLK_FREQ_MHZ__SYSCLK_FREQ_MHZ_bm) >>
                   SEP_EFUSE_MAP__SYSCLK_FREQ_MHZ__SYSCLK_FREQ_MHZ_bp);
    if (pll_freq_mhz == 0u) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_PLL_FUSES_BLANK);
        simputs("PLL_FUSES_BLANK\n");
        report_status(STATUS_TYPE_INFO, SEP_MSG_REF_CLK_SELECTED);
        return (uint16_t)SMU_REF_CLK_FREQ_MHZ;
    }

    // An override may wait for lock without a timeout ([SEP-ROM-CPU-080]), so
    // the wait is announced on the status channel first: a part that never
    // locks is left showing this status.
    report_status(STATUS_TYPE_INFO, SEP_MSG_WAIT_FOR_PLL_LOCK);
    simputs("PLL_WAIT_LOCK\n");
    return sep_pll_lock_and_select(pll_freq_mhz);
}

__attribute__((weak)) uint16_t sep_pll_lock_and_select(uint16_t freq_mhz) {
    (void)freq_mhz;
    simputs("PLL_NOT_IMPLEMENTED\n");
    report_status(STATUS_TYPE_INFO, SEP_MSG_REF_CLK_SELECTED);
    return (uint16_t)SMU_REF_CLK_FREQ_MHZ;
}
