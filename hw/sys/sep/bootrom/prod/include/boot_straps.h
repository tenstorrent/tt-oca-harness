/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Boot strap parsing for OROM.
//
// Reads latched strap values from the SMC external mandatory window and
// provides structured access for boot path decisions using the addresses from
// sep_smc_interface.h.
//
// Strap bits (SEP↔SMC interface contract, see sep_smc_interface.h). Bit index is
// the GPIO index; STRAPS_HI[N] is GPIO N+32. Canonical source is
// hw/sys/smc/regs/blocks/straps/straps.rdl.
//   STRAPS_LO[13]: bypass_sram_repair — skip memory repair
//   STRAPS_LO[19]: boot_recovery       — recovery mode (wait for SMC manifest)
//   STRAPS_LO[20]: bl0_pll_clk         — use PLL instead of refclk
//   STRAPS_LO[21]: status_report_disable — disable status ring buffer
//   STRAPS_LO[25]: primary_chiplet     — primary chiplet (load from SPI)
//   STRAPS_HI[22]: mbist_bypass        — ignore power-on MBIST results (GPIO 54)
//   STRAPS_HI[26]: rotate_update       — alternate primary/backup manifest slot (GPIO 58)

#pragma once

#include <stdbool.h>
#include <stdint.h>

// Boot strap configuration parsed from the SMC captured-GPIO registers.
// All fields are simple booleans derived from individual strap bits.
struct boot_straps {
    bool primary_chiplet;       // true = primary (SPI boot); false = secondary (wait SMC)
    bool boot_recovery;         // true = recovery mode (even if primary, wait SMC manifest)
    bool rotate_update;         // true = use rotated manifest slot (primary ↔ backup)
    bool status_report_disable; // true = skip status ring buffer init
    bool bl0_pll_clk;           // true = init PLL from fuses; false = use refclk

    // Raw register values kept for diagnostic output.
    uint32_t raw_lo;
    uint32_t raw_hi;
};

// Initialize strap configuration by reading the SMC captured-GPIO registers.
// Must be called early in rom_main (before any strap-dependent decisions).
void init_straps(struct boot_straps *straps);

// Convenience: determine boot source based on straps.
//   PRIMARY + !RECOVERY → boot from SPI flash
//   PRIMARY +  RECOVERY → wait for manifest from SMC SRAM
//  !PRIMARY             → wait for manifest from SMC SRAM (secondary chiplet)
static inline bool boot_from_spi(const struct boot_straps *straps) {
    return straps->primary_chiplet && !straps->boot_recovery;
}
