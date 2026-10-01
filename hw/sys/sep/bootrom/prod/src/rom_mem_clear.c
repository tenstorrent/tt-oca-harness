/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OROM memory clear implementation (Step N).
//
// Clears SEP EXT SRAM to zero for deterministic state before manifest load
// and BL1 execution:
//   write_zeros(SEP_EXT_SRAM_BASE, SEP_SRAM_SIZE, false)
//
// Uses a CPU word loop rather than DMA because the DMA engine is a copy
// engine (src→dst) and does not have a dedicated "fill" mode.
//
// Controlled by SRAM_SCRUB_BYTES (build knob, default 0 = disabled):
//   make -C fw/sep/bootcode clean all SRAM_SCRUB_BYTES=0x40000
// Default is disabled (0) because 256 KiB of CPU stores (~65K AXI writes)
// is extremely slow in RTL simulation.  Manifest DMA will overwrite the
// relevant region anyway, so skipping the scrub is safe for DV.

#include <stdint.h>

#include "oca_boot.h"
#include "errors.h"
#include "rom_mmio.h"

// Generated register map (provides SEP_TOP_SEP_SRAM_BASE_ADDR/SIZE).
#include "sep.h"

#define SRAM_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SRAM_SIZE ((uint32_t)SEP_TOP_SEP_SRAM_SIZE)

#ifndef SRAM_SCRUB_BYTES
#define SRAM_SCRUB_BYTES 0
#endif

void rom_clear_ext_sram(void) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_EXT_SRAM_CLEAR_START);
    simputshex32("SRAM_SCRUB_CFG=", (uint32_t)SRAM_SCRUB_BYTES);

#if SRAM_SCRUB_BYTES > 0
    uint32_t scrub = (uint32_t)SRAM_SCRUB_BYTES;
    if (scrub > SRAM_SIZE) scrub = SRAM_SIZE;

    simputshex32("SRAM_SCRUB_LEN=", scrub);
    volatile uint32_t *p = (volatile uint32_t *)(uintptr_t)SRAM_BASE;
    uint32_t words = scrub / 4u;

    for (uint32_t i = 0; i < words; ++i) {
        p[i] = 0u;
        // Progress every 16K words (64 KiB).
        if ((i & 0x3FFF) == 0) {
            simputshex32("SRAM_CLR_PROG=", i * 4u);
        }
    }
    simputs("SRAM_CLR_OK\n");
#else
    simputs("SRAM_CLR_SKIP\n");
#endif

    report_status(STATUS_TYPE_INFO, SEP_MSG_EXT_SRAM_CLEAR_DONE);
}
