/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Clock source selection for the ROM.
//
// SEP owns no PLL. The PLL, its lock-detect status, and the sysclk/peripheral
// clock mux all live in SMC register space, reached through the SMC window
// (`sep_get_smc_base() + offset`); this code only selects the SMC-owned PLL as
// SEP's clock source in place of the 100 MHz reference clock, and only when the
// `bl0_pll_clk` strap asks for it. With the strap clear the ROM stays on refclk
// and touches no PLL register.
//
// The mux encoding below is a placeholder: OCAH does not distinguish chiplet
// types, so there is one lock-plus-mux path for every part. An adopter whose
// platform needs a different sysclk source, divider, or per-chiplet mux fits it
// here.

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

    const uint32_t smc_base = sep_get_smc_base();
    simputshex32("SMC_BASE=", smc_base);

    // smu_pll_sysclk is an 11-bit field holding the configured sysclk frequency in
    // MHz. It lives inside the SEP_SPI_CTRL_FIELD_EN fuse word -- that register is
    // simply where the RDL places the field, not a separate enable. Sensing
    // completed in [C4]. Zero means the fuses are blank; fall back to refclk.
    uint32_t spi_ctrl = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR);
    uint16_t pll_freq_mhz =
        (uint16_t)((spi_ctrl & SEP_EFUSE_MAP__SEP_SPI_CTRL_FIELD_EN__SMU_PLL_SYSCLK_bm) >>
                   SEP_EFUSE_MAP__SEP_SPI_CTRL_FIELD_EN__SMU_PLL_SYSCLK_bp);
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
