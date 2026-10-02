// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Default external flash controller hooks: the controller is reported absent,
// so spi_init() fails, which rom_main() treats as non-fatal. Every symbol is
// weak; an integrator's driver, added through the Makefile's
// NONFREE_BOOTCODE_SOURCES, overrides them at link time.

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
    simputs("SPI_STUB_SKIP\n");
    return 1u;
}

__attribute__((weak)) uint32_t spi_reinit(void) {
    return 1u;
}

__attribute__((weak)) bool spi_primary_tlv_failed(void) {
    return true;
}
