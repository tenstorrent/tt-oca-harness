// SPDX-License-Identifier: Apache-2.0
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
// Replace this stub with the real Cadence xSPI driver once the OSS DUT provides
// that controller (see cpu.toml TODO / sep-rom-non-secure-boot-design.md).

#include <stdbool.h>
#include <stdint.h>

#include "sep_spi.h"
#include "rom_virt_console.h"

void spi_set_rotate(bool rotate)
{
    (void)rotate;
}

void spi_set_sysclk(uint16_t freq_mhz)
{
    (void)freq_mhz;
}

uint32_t spi_init(void)
{
    // Non-zero -> the OSS `sep` has no Cadence xSPI, so SPI is unavailable and
    // the ROM takes its non-SPI (SMC-SRAM) manifest path. The testbench serves
    // the manifest+BL1 from a behavioral memory at the SMC-SRAM base.
    simputs("SPI_STUB_SKIP\n");
    return 1u;
}

uint32_t spi_reinit(void)
{
    return 1u;
}

bool spi_primary_tlv_failed(void)
{
    return true;
}
