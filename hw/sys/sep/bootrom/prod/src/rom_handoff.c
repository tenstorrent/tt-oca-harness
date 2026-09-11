/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OROM BL1 handoff: find image, copy to ICCM, jump.
//
// BL1 handoff sequence:
//   1. find_toc_entry(SEP_BL1) — scan TOC for BL1 image
//   2. sep_dma_copy()          — DMA BL1 from SRAM to its ICCM load address
//   3. jump_to_bl1()           — transfer control to BL1 entry point
//
// Manifest format: manifest_t + toc_header + toc_entry[].
//
// BL1 executes from ICCM: the IFU fetches it there, and vector.S's warm-reset
// handler check only accepts an ICCM address.  Nothing BL1 loads or stores can
// be in ICCM, though, so the blob copied here is BL1's .text plus the load image
// of its .rodata/.data, and BL1's own _start copies that second part into DCCM --
// reading it from SRAM via bl0_state.bl1_image_src_addr, since the ICCM copy is
// not readable to it either.
//
// The manifest payload (including BL1) is already in SRAM after the
// SPI DMA load.  We copy it to BL1's link address so the PC-relative
// and absolute addresses in the binary are correct.

#include <stdint.h>

#include "bl0_state.h"
#include "manifest.h"
#include "errors.h"
#include "sep_dma.h"

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Scan the TOC for the first entry matching the given image type.
static const struct toc_entry *find_toc_entry(const manifest_t *m, uint64_t image_type) {
    const struct toc_header *toc = (const struct toc_header *)manifest_payload_address(m);
    uint32_t n = (uint32_t)toc->image_count;
    for (uint32_t i = 0; i < n; ++i) {
        if (toc->images[i].type == image_type) {
            return &toc->images[i];
        }
    }
    return (const struct toc_entry *)0;
}

// The copy must go through the DMA, not a CPU memcpy. ICCM and DCCM share VeeR
// region 0xC, so el2_lsu_addrcheck treats any 0xCxxxxxxx address as DCCM's and
// faults the ones outside DCCM's offset range: a store to ICCM raises an
// unmapped access fault and never reaches the bus. The DMA engine is a separate
// crossbar master and does reach the ICCM window.

// Jump to BL1 entry point.  Does not return.
__attribute__((noreturn)) static void jump_to_bl1(uint32_t entry_addr) {
    // fence.i flushes IFU pipeline so freshly written ICCM code is visible.
    // fence completes pending stores.
    simputs("PRE_JUMP\n");
    __asm__ volatile("csrw mepc, %0\n"
                     "fence.i\n"
                     "fence\n"
                     "mret\n"
                     :
                     : "r"(entry_addr)
                     : "memory");
    __builtin_unreachable();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

uint32_t rom_handoff_bl1(const manifest_t *m) {
    report_status(STATUS_TYPE_INFO, SEP_MSG_COPY_AND_EXEC_IMAGE);

    const struct toc_header *toc = (const struct toc_header *)manifest_payload_address(m);

    // ── Step 1: Find BL1 in the TOC ──
    const struct toc_entry *bl1 = find_toc_entry(m, IMAGE_TYPE_SEP_BL1);
    if (!bl1) {
        simputs("NO_BL1_IMAGE\n");
        return MANIFEST_ERR_NO_BL1_IMAGE;
    }

    uint32_t load_addr = (uint32_t)bl1->load_addr;
    uint32_t img_length = (uint32_t)bl1->length;
    uint32_t entry_off = (uint32_t)bl1->entry_point;
    uint32_t img_offset = (uint32_t)bl1->offset;

    report_status(STATUS_TYPE_INFO, SEP_MSG_BL1_FOUND);
    simputshex32("BL1_TYPE=", (uint32_t)bl1->type);
    simputshex32("LOAD=", load_addr);
    simputshex32("LEN=", img_length);
    simputshex32("ENTRY=", entry_off);

    uint32_t chk = check_bl1_image(bl1);
    if (chk) {
        simputs(chk == 1 ? "BL1_ADDR_RANGE\n" : "BL1_ENTRY_RANGE\n");
        return MANIFEST_ERR_BL1_BAD_ADDR;
    }

    if (img_length == 0u || img_length > SEP_IRAM_SIZE) {
        simputs("BL1_SIZE\n");
        return MANIFEST_ERR_BL1_TOO_LARGE;
    }

    img_length = (img_length + 3u) & ~3u;

    const uint8_t *bl1_data = (const uint8_t *)toc + img_offset;

    // ── Step 2: Copy BL1 to its ICCM load address ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_BL1_COPY);
    simputshex32("COPY_SRC=", (uint32_t)(uintptr_t)bl1_data);
    simputshex32("COPY_DST=", load_addr);
    simputshex32("COPY_LEN=", img_length);

    uint32_t dma_err = sep_dma_copy(load_addr, (uint32_t)(uintptr_t)bl1_data, img_length);
    if (dma_err) {
        simputs("BL1_COPY_FAIL\n");
        return MANIFEST_ERR_BL1_BAD_ADDR;
    }
    simputs("BL1_COPIED\n");

    // BL1 needs the SRAM source, not the ICCM copy, to reach the load image of
    // its own .rodata/.data: it executes from ICCM but cannot read ICCM.
    get_bl0_state()->bl1_image_src_addr = (uint32_t)(uintptr_t)bl1_data;

    // ── Step 3: Jump to BL1 ──
    uint32_t entry_addr = load_addr + entry_off;

    report_status(STATUS_TYPE_INFO, SEP_MSG_EXEC_IMAGE);
    report_status(STATUS_TYPE_INFO, SEP_MSG_STARTING_BL1);
    report_status(STATUS_TYPE_INFO_EXT, (uint16_t)(entry_addr >> 16));
    report_status(STATUS_TYPE_INFO_EXT, (uint16_t)(entry_addr & 0xFFFF));
    simputshex32("BL1_JUMP=", entry_addr);

    jump_to_bl1(entry_addr);

    // Should never reach here.
    return MANIFEST_ERR_NO_BL1_IMAGE;
}
