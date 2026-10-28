/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP SRAM clears: the optional scrub before any manifest is staged ([S15]),
// and the clear between SPI manifest slots. Both use the secure DMA zero fill.
//
// The scrub is controlled by SRAM_SCRUB_BYTES (build knob; 0x40000 clears all of
// SEP SRAM). The Makefile sets the default.

#include <stdint.h>

#include "errors.h"
#include "harden.h"
#include "oca_boot.h"
#include "rom_mmio.h"
#include "rom_virt_console.h"
#include "sep_dma.h"

// Generated register map (provides SEP_TOP_SEP_SRAM_BASE_ADDR/SIZE).
#include "sep.h"

#define SRAM_BASE ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SRAM_SIZE ((uint32_t)SEP_TOP_SEP_SRAM_SIZE)

#ifndef SRAM_SCRUB_BYTES
#define SRAM_SCRUB_BYTES 0
#endif

#if (SRAM_SCRUB_BYTES % 4) != 0
#error "SRAM_SCRUB_BYTES must be a whole number of 32-bit words"
#endif

// Zeroes [SRAM_BASE, SRAM_BASE + len) and reads back its first, middle and last
// words, which must be zero. The readback catches a fill the engine reported
// complete but did not write.
static uint32_t sram_zero(uint32_t len) {
    const uint32_t err = sep_dma_zero(SRAM_BASE, len);
    if (err != 0u || harden_u32(err) != 0u) {
        return err != 0u ? err : SEP_DMA_ERR_TRANSFER;
    }
    const uint32_t mid = SRAM_BASE + ((len / 2u) & ~3u);
    const uint32_t last = SRAM_BASE + len - 4u;
    const uint32_t seen = mmio_read32(SRAM_BASE) | mmio_read32(mid) | mmio_read32(last);
    if (seen != 0u || harden_u32(seen) != 0u) {
        report_status(STATUS_TYPE_WARN, SEP_MSG_DMA_ERROR);
        return SEP_DMA_ERR_TRANSFER;
    }
    return 0u;
}

uint32_t rom_clear_ext_sram(void) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_EXT_SRAM_CLEAR_START);
    simputshex32("SRAM_SCRUB_CFG=", (uint32_t)SRAM_SCRUB_BYTES);

#if SRAM_SCRUB_BYTES > 0
    uint32_t scrub = (uint32_t)SRAM_SCRUB_BYTES;
    if (scrub > SRAM_SIZE) scrub = SRAM_SIZE;

    simputshex32("SRAM_SCRUB_LEN=", scrub);
    const uint32_t err = sram_zero(scrub);
    if (err != 0u) {
        simputs("SRAM_CLR_FAIL\n");
        return err;
    }
    simputs("SRAM_CLR_OK\n");
#else
    simputs("SRAM_CLR_SKIP\n");
#endif

    report_status(STATUS_TYPE_INFO, SEP_MSG_EXT_SRAM_CLEAR_DONE);
    return 0u;
}

uint32_t rom_clear_sram_for_retry(void) {
    if (sram_zero(SRAM_SIZE) != 0u) {
        simputs("SRAM_RETRY_CLR_FAIL\n");
        return OCA_BOOT_ERR_DMA;
    }
    return 0u;
}
