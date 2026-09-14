// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// OSS SPI stub for the SEP boot ROM (non-secure ROM boot test).
//
// The production sep_spi.c drives the Cadence xSPI (octal) controller. The OSS
// `sep` DUT exposes only the OpenTitan Quad spi_host and has NO Cadence xSPI, so
// the real SPI init would write to an absent register block. For the OSS
// non-secure ROM boot test we therefore skip SPI entirely: spi_init() reports
// failure, which is non-fatal in rom_main() -- the ROM then skips the SPI
// "primary" manifest and boots from the SMC-SRAM manifest path instead. No
// Cadence registers are touched, so the real ROM still runs end-to-end.
//
// All symbols are WEAK: a build that carries the real Cadence xSPI driver
// (companion-supplied, injected via the Makefile NONFREE_BOOTCODE_SOURCES
// hook) overrides them at link time -- same weak-stub/strong-override pattern
// as the SMC prod ROM drivers.

#include <stdbool.h>
#include <stdint.h>

#include "sep_spi.h"
#include "rom_virt_console.h"

__attribute__((weak)) void spi_set_rotate(bool rotate) {
    (void)rotate;
}

__attribute__((weak)) void spi_set_sysclk(uint16_t freq_mhz) {
    (void)freq_mhz;
}

__attribute__((weak)) uint32_t spi_init(void) {
    // Non-zero -> the OSS `sep` has no Cadence xSPI, so SPI is unavailable and
    // the ROM takes its non-SPI (SMC-SRAM) manifest path. The testbench serves
    // the manifest+BL1 from a behavioral memory at the SMC-SRAM base.
    simputs("SPI_STUB_SKIP\n");
    return 1u;
}

__attribute__((weak)) uint32_t spi_reinit(void) {
    return 1u;
}

__attribute__((weak)) bool spi_primary_tlv_failed(void) {
    return true;
}
