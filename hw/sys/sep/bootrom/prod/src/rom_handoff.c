/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OROM BL1 handoff: find image, copy to SRAM, jump.
//
// BL1 handoff sequence:
//   1. find_toc_entry(SEP_BL1) — scan TOC for BL1 image
//   2. copy_bl1_to_sram()      — CPU memcpy BL1 to SRAM load address
//   3. jump_to_bl1()           — transfer control to BL1 entry point
//
// Manifest format: manifest_t + toc_header + toc_entry[].
//
// BL1 is a single flat binary (.text + .rodata + .data + .bss) linked
// to an SRAM address.  Both IFU and LSU access SRAM through the AXI
// system bus, so no ICCM/DCCM split is needed.
//
// The manifest payload (including BL1) is already in SRAM after the
// SPI DMA load.  We copy it to BL1's link address so the PC-relative
// and absolute addresses in the binary are correct.

#include <stdint.h>

#include "manifest.h"
#include "errors.h"

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

// Copy BL1 image to its SRAM load address via CPU memcpy.
// Both src (manifest payload in SRAM) and dst (BL1 link address in SRAM)
// are LSU-accessible.
static void copy_bl1_to_sram(const uint8_t *src, uint32_t dest_addr, uint32_t length) {
    volatile uint32_t *dst = (volatile uint32_t *)(uintptr_t)dest_addr;
    const uint32_t *src32 = (const uint32_t *)src;
    uint32_t words = length >> 2;
    for (uint32_t i = 0; i < words; ++i) {
        dst[i] = src32[i];
    }
    uint32_t rem = length & 3u;
    if (rem) {
        uint32_t last = 0;
        const uint8_t *tail = (const uint8_t *)&src32[words];
        for (uint32_t j = 0; j < rem; ++j) last |= (uint32_t)tail[j] << (8u * j);
        dst[words] = last;
    }
}

// Jump to BL1 entry point.  Does not return.
__attribute__((noreturn)) static void jump_to_bl1(uint32_t entry_addr) {
    // fence.i flushes IFU pipeline so freshly written SRAM code is visible.
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

    if (img_length == 0u || img_length > SEP_SRAM_SIZE) {
        simputs("BL1_SIZE\n");
        return MANIFEST_ERR_BL1_TOO_LARGE;
    }

    img_length = (img_length + 3u) & ~3u;

    const uint8_t *bl1_data = (const uint8_t *)toc + img_offset;

    // ── Step 2: Copy BL1 to SRAM load address ──
    report_status(STATUS_TYPE_INFO, SEP_MSG_BL1_COPY);
    simputshex32("COPY_SRC=", (uint32_t)(uintptr_t)bl1_data);
    simputshex32("COPY_DST=", load_addr);
    simputshex32("COPY_LEN=", img_length);

    copy_bl1_to_sram(bl1_data, load_addr, img_length);
    simputs("BL1_COPIED\n");

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
