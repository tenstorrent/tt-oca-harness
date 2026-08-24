/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OpenTitan SPI Host driver — timing/device parameter table.
 *
 * Every tunable SPI timing/device parameter lives here. Supporting a new attached
 * flash part is a one-row edit: add an ot_spi_params_t entry. Entry [0] is the
 * safe default and is used unless another profile is selected. The table is const
 * and lands in .rodata (placed in DCCM by the linker script).
 */
#ifndef SEP_OT_SPI_PROFILES_H
#define SEP_OT_SPI_PROFILES_H

#include "sep_ot_spi.h"
#include "sep_ot_flash_opcodes.h"

static const ot_spi_params_t ot_spi_profiles[] = {
    /* [0] Default: portable standard read — opcode 0x03, single lane, 3-byte
     * address, no dummy cycles, SPI mode 0, moderate CS timing, ~25 MHz SCK.
     * Matches the settings the standalone controller tests use. */
    {
        .sck_mhz = 25u,
        .cpol = 0u,
        .cpha = 0u,
        .full_cyc = 1u, /* sample a full cycle late: at
                         * 25 MHz the SCK->flash->data
                         * round-trip exceeds the
                         * half-cycle window, so
                         * half-cycle sampling reads each
                         * bit one SCK early. */
        .csnidle = 2u,
        .csnlead = 2u,
        .csntrail = 2u,
        .read_opcode = OT_SPI_OP_READ, /* 0x03 */
        .dummy_cycles = 0u,
        .data_width = OT_SPI_WIDTH_STD,
        .addr_bytes = 3u,
        .rx_watermark = 4u,
        .flags = OT_SPI_PF_CYCLE_ELIGIBLE,
    },
    /* [1] Example alternate: fast read (0x0B) with 8 dummy cycles, single lane.
     * Present to show that adding a device is a one-row edit; not the default. */
    {
        .sck_mhz = 25u,
        .cpol = 0u,
        .cpha = 0u,
        .full_cyc = 1u, /* full-cycle sampling (see [0]) */
        .csnidle = 2u,
        .csnlead = 2u,
        .csntrail = 2u,
        .read_opcode = OT_SPI_OP_READ_FAST, /* 0x0B */
        .dummy_cycles = 8u,
        .data_width = OT_SPI_WIDTH_STD,
        .addr_bytes = 3u,
        .rx_watermark = 4u,
        .flags = 0u,
    },
};

#define OT_SPI_PROFILE_COUNT (sizeof(ot_spi_profiles) / sizeof(ot_spi_profiles[0]))

/* Boot profile index (build-time). 0 = safe default; override with
 * -DBOOT_OT_SPI_PROFILE=<n> (or `make BOOT_OT_SPI_PROFILE=<n>`) to boot a
 * different attached part. ot_spi_init() selects it via ot_spi_select_profile(). */
#ifndef BOOT_OT_SPI_PROFILE
#define BOOT_OT_SPI_PROFILE 0
#endif
_Static_assert(BOOT_OT_SPI_PROFILE < OT_SPI_PROFILE_COUNT,
               "BOOT_OT_SPI_PROFILE out of range for ot_spi_profiles[]");

#endif /* SEP_OT_SPI_PROFILES_H */
