/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Boot strap parsing implementation for OROM.
//
// Reads captured GPIO straps from the SMC external supplementary window and
// populates a boot_straps structure.

#include "boot_straps.h"
#include "rom_mmio.h"
#include "errors.h"
#include "sep_smc_interface.h"

void init_straps(struct boot_straps *straps) {
    const uint32_t lo = smc_read_straps_lo();
    const uint32_t hi = smc_read_straps_hi();

    straps->raw_lo = lo;
    straps->raw_hi = hi;

    // Bit positions defined in sep_smc_interface.h (SEP↔SMC interface contract).
    straps->primary_chiplet = !!(lo & SMC_STRAP_PRIMARY_CHIPLET_MASK);
    straps->boot_recovery = !!(lo & SMC_STRAP_BOOT_RECOVERY_MASK);
    straps->rotate_update = !!(hi & SMC_STRAP_ROTATE_UPDATE_MASK);
    straps->status_report_disable = !!(lo & SMC_STRAP_STATUS_RPT_DISABLE_MASK);
    straps->bl0_pll_clk = !!(lo & SMC_STRAP_BL0_PLLCLK_MASK);

    // Diagnostic output (always, regardless of channel enables).
    simputshex32("STRAPS_LO=", lo);
    simputshex32("STRAPS_HI=", hi);

    simputsdec24("STRAP primary=", straps->primary_chiplet);
    simputsdec24(" recovery=", straps->boot_recovery);
    simputsdec24(" rotate=", straps->rotate_update);
    simputsdec24(" status_dis=", straps->status_report_disable);
    simputsdec24(" pllclk=", straps->bl0_pll_clk);
}
